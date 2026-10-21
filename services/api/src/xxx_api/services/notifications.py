"""Transactional notice fanout and bounded, fenced, at-least-once SMTP delivery."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import compare_digest
from hmac import new as hmac_new
from uuid import UUID, uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from xxx_api.config import Settings
from xxx_api.domain.auth import AuditEventType, UserStatus
from xxx_api.domain.roles import Role
from xxx_api.email import EmailDeliveryError, NoticeSender
from xxx_api.models.analysis import OutboxEvent
from xxx_api.models.identity import User
from xxx_api.models.notifications import Notification
from xxx_api.services.audit import append_audit_event

# No user-supplied strings or commercial facts enter email. Follow the authenticated screen
# for current authoritative details, especially when older notices arrive after newer events.
TEMPLATES: dict[str, tuple[Role, str, str, str]] = {
    "buyer.quote_issued": (
        Role.BUYER,
        "Quotation available",
        "A quotation is available for review.",
        "/orders",
    ),
    "buyer.request_rejected": (
        Role.BUYER,
        "Quote request updated",
        "A quote request was declined. Sign in to read the owner's reason.",
        "/get-a-quote",
    ),
    "buyer.order_accepted": (
        Role.BUYER,
        "Quotation accepted",
        "Your quotation was accepted. Payment is not yet confirmed.",
        "/orders",
    ),
    "buyer.payment_confirmed": (
        Role.BUYER,
        "Payment confirmed",
        "Payment was confirmed. Printing still requires operator preparation and approval.",
        "/orders",
    ),
    "buyer.order_updated": (
        Role.BUYER,
        "Order status updated",
        "An order's production or fulfillment status has changed.",
        "/orders",
    ),
    "owner.request_submitted": (
        Role.OWNER,
        "New quote request",
        "A buyer submitted a quote request for analysis.",
        "/operations",
    ),
    "owner.analysis_ready": (
        Role.OWNER,
        "Analysis updated",
        "Model analysis has finished. Review its evidence before issuing a quotation.",
        "/operations",
    ),
    "owner.analysis_failed": (
        Role.OWNER,
        "Analysis needs attention",
        "Model analysis failed and needs review.",
        "/operations",
    ),
    "owner.quote_accepted": (
        Role.OWNER,
        "Quotation accepted",
        "A buyer accepted a quotation. Payment is not yet confirmed.",
        "/operations",
    ),
    "owner.payment_confirmed": (
        Role.OWNER,
        "Paid order needs preparation",
        "Payment was confirmed. Review the production queue and readiness checks.",
        "/operations",
    ),
    "owner.print_failed": (
        Role.OWNER,
        "Print needs attention",
        "A print or quality check failed. Review the operator record.",
        "/operations",
    ),
}


def _utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(UTC)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _destination(settings: Settings, value: str) -> str:
    return hmac_new(
        settings.token_hash_secret.get_secret_value().encode(),
        b"workflow-destination/v1\x00" + value.encode(),
        sha256,
    ).hexdigest()


async def request_notice(
    session: AsyncSession,
    code: str,
    aggregate_type: str,
    aggregate_id: UUID,
    recipient_id: UUID | None = None,
) -> None:
    role = TEMPLATES[code][0]
    if role is Role.OWNER:
        recipient_id = await session.scalar(
            select(User.id).where(User.role == Role.OWNER, User.owner_slot == "primary")
        )
    if recipient_id is None:
        return  # No provisioned owner yet; do not invent a contact address.
    event_id = uuid4()
    session.add(
        OutboxEvent(
            id=event_id,
            topic="notification.requested",
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            idempotency_key=f"notification:{event_id}",
            payload={
                "schemaVersion": 1,
                "recipientUserId": str(recipient_id),
                "templateCode": code,
            },
            available_at=_utc(),
            attempt_count=0,
        )
    )


def _eligible(user: User | None, code: str) -> bool:
    return bool(
        user
        and user.status is UserStatus.ACTIVE
        and user.email
        and user.email_verified_at
        and user.role is TEMPLATES[code][0]
    )


async def publish_notifications(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    limit: int = 20,
) -> int:
    if not settings.workflow_notifications_enabled:
        return 0
    now = _utc()
    count = 0
    async with sessions() as session:
        events = list(
            await session.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.topic == "notification.requested",
                    OutboxEvent.published_at.is_(None),
                    OutboxEvent.available_at <= now,
                )
                .order_by(OutboxEvent.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for event in events:
            changed = await session.scalar(
                update(OutboxEvent)
                .where(OutboxEvent.id == event.id, OutboxEvent.published_at.is_(None))
                .values(published_at=now, attempt_count=OutboxEvent.attempt_count + 1)
                .returning(OutboxEvent.id)
            )
            if changed is None:
                continue
            payload = event.payload
            try:
                if (
                    set(payload) != {"schemaVersion", "recipientUserId", "templateCode"}
                    or type(payload["schemaVersion"]) is not int
                    or payload["schemaVersion"] != 1
                    or payload["templateCode"] not in TEMPLATES
                ):
                    raise ValueError
                recipient_id = UUID(str(payload["recipientUserId"]))
                code = str(payload["templateCode"])
            except (ValueError, TypeError):
                event.last_error_code = "invalid_notification_payload"
                continue
            user = await session.get(User, recipient_id)
            eligible = _eligible(user, code)
            session.add(
                Notification(
                    outbox_event_id=event.id,
                    recipient_user_id=user.id if user else None,
                    template_code=code,
                    template_version="1",
                    channel="email",
                    destination_digest=_destination(
                        settings, (user.email or str(user.id)) if user else str(recipient_id)
                    ),
                    status="pending" if eligible else "dead_lettered",
                    available_at=now,
                    attempt_count=0,
                    last_error_code=None if eligible else "recipient_unavailable",
                )
            )
            count += 1
        await session.commit()
    return count


async def deliver_notifications(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    sender: NoticeSender,
    *,
    limit: int = 10,
    now: datetime | None = None,
) -> int:
    if not settings.workflow_notifications_enabled:
        return 0
    started = _utc(now)
    async with sessions() as session:
        # A crash during the last allowed submission has an unknown SMTP outcome. Do not
        # strand it forever or silently retry beyond the bound; surface an owner dead letter.
        await session.execute(
            update(Notification)
            .where(
                Notification.status.in_(["pending", "failed"]),
                Notification.attempt_count >= settings.notification_max_attempts,
                or_(
                    Notification.lease_expires_at.is_(None),
                    Notification.lease_expires_at <= started,
                ),
            )
            .values(
                status="dead_lettered",
                last_error_code="delivery_uncertain",
                lease_token=None,
                lease_expires_at=None,
            )
        )
        await session.commit()
    eligible = (
        Notification.status.in_(["pending", "failed"]),
        Notification.available_at <= started,
        Notification.attempt_count < settings.notification_max_attempts,
        or_(Notification.lease_expires_at.is_(None), Notification.lease_expires_at <= started),
    )
    async with sessions() as session:
        ids = list(
            await session.scalars(
                select(Notification.id)
                .where(*eligible)
                .order_by(Notification.available_at, Notification.id)
                .limit(limit)
            )
        )
    count = 0
    for notification_id in ids:
        token = uuid4()
        claimed_at = _utc(now)
        async with sessions() as session:
            claimed = await session.scalar(
                update(Notification)
                .where(Notification.id == notification_id, *eligible)
                .values(
                    lease_token=token,
                    lease_expires_at=claimed_at + timedelta(minutes=2),
                    attempt_count=Notification.attempt_count + 1,
                )
                .returning(Notification.id)
            )
            if claimed is None:
                await session.rollback()
                continue
            row = await session.get(Notification, notification_id)
            assert row is not None
            user = await session.get(User, row.recipient_user_id) if row.recipient_user_id else None
            attempts = row.attempt_count
            error_code = None
            if row.template_version != "1" or row.template_code not in TEMPLATES:
                error_code = "template_unavailable"
            elif not _eligible(user, row.template_code):
                error_code = "recipient_unavailable"
            elif user and not compare_digest(
                row.destination_digest, _destination(settings, user.email or str(user.id))
            ):
                error_code = "recipient_changed"
            recipient = (user.email or "") if user else ""
            template = TEMPLATES.get(row.template_code)
            await session.commit()  # Release all DB locks before the external SMTP boundary.
        count += 1
        message_id = (
            f"<workflow-{notification_id.hex}@{str(settings.email_sender_address).split('@')[1]}>"
        )
        status = "dead_lettered" if error_code else "sent"
        if error_code is None and template:
            _, subject, text, path = template
            link = f"{str(settings.public_web_url).rstrip('/')}{path}"
            body = f"{text}\n\nSign in for current details:\n{link}\n"
            if settings.environment != "production":
                body = "TEST ENVIRONMENT — not a real payment or print.\n\n" + body
            try:
                await sender.send_notice(
                    recipient, subject=subject, body=body, message_id=message_id
                )
            except EmailDeliveryError:
                error_code = "smtp_unavailable"
                status = (
                    "dead_lettered" if attempts >= settings.notification_max_attempts else "failed"
                )
        async with sessions() as session:
            await session.execute(
                update(Notification)
                .where(Notification.id == notification_id, Notification.lease_token == token)
                .values(
                    status=status,
                    last_error_code=error_code,
                    lease_token=None,
                    lease_expires_at=None,
                    available_at=_utc(now) + timedelta(seconds=min(3600, 60 * 2 ** (attempts - 1))),
                    sent_at=_utc(now) if status == "sent" else None,
                    provider_message_id=message_id if status == "sent" else None,
                )
            )
            await session.commit()
    return count


async def retry_notification(session: AsyncSession, owner: User, notification_id: UUID) -> None:
    # HTTP also requires recent MFA, trusted origin and session CSRF.
    from xxx_api.services.commerce import (
        WorkflowConflictError,
        WorkflowNotFoundError,
        require_owner,
    )

    require_owner(owner)
    row = await session.get(Notification, notification_id)
    if row is None:
        raise WorkflowNotFoundError
    previous_attempts = row.attempt_count
    changed = await session.scalar(
        update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.status == "dead_lettered",
            Notification.lease_token.is_(None),
        )
        .values(status="pending", attempt_count=0, available_at=_utc(), last_error_code=None)
        .returning(Notification.id)
    )
    if changed is None:
        await session.rollback()
        raise WorkflowConflictError("Only an unleased dead letter can be retried.")
    append_audit_event(
        session,
        AuditEventType.NOTIFICATION_RETRY_REQUESTED,
        occurred_at=_utc(),
        actor_user_id=owner.id,
        details={"notification_id": str(notification_id), "previous_attempts": previous_attempts},
    )
    await session.commit()
