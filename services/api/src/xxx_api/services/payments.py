"""Checkout hints and authoritative, idempotent payment reconciliation."""

import hashlib
import hmac
import json
import re
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from xxx_api.config import Settings
from xxx_api.domain.auth import AuditEventType, UserStatus
from xxx_api.domain.roles import Role
from xxx_api.models.commerce import Order, PaymentIntent, PaymentProviderEvent
from xxx_api.models.identity import User
from xxx_api.razorpay import (
    GatewayUnavailableError,
    ProviderOrder,
    ProviderPayment,
    RazorpayGateway,
)
from xxx_api.services.commerce import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    audit,
    compare_version,
    get_order,
    record_captured_payment,
    utc,
)

PAYABLE = {"payment_pending", "payment_processing", "payment_failed", "payment_review"}
EVENTS = {"payment.captured", "order.paid", "payment.authorized", "payment.failed"}


def configured(settings: Settings) -> None:
    if not settings.razorpay_enabled:
        raise GatewayUnavailableError("Online payment is not configured yet.")


def account_matches(intent: PaymentIntent, settings: Settings) -> None:
    configured(settings)
    if intent.provider != "razorpay" or intent.provider_key_id != settings.razorpay_key_id:
        raise WorkflowConflictError("This payment needs owner investigation before retrying.")


def match_order(intent: PaymentIntent, order: ProviderOrder) -> None:
    if (
        order.receipt != intent.payment_reference
        or order.amount != intent.amount_paise
        or order.currency != intent.currency
        or order.currency != "INR"
        or (intent.provider_order_id is not None and order.id != intent.provider_order_id)
    ):
        raise WorkflowConflictError("Provider order does not match the accepted payment.")


def match_capture(intent: PaymentIntent, order: ProviderOrder, payment: ProviderPayment) -> None:
    match_order(intent, order)
    if (
        payment.order_id != order.id
        or payment.amount != intent.amount_paise
        or payment.currency != "INR"
        or payment.status != "captured"
        or not payment.captured
        or payment.amount_refunded != 0
        or order.status != "paid"
        or order.amount_paid != intent.amount_paise
        or order.amount_due != 0
    ):
        raise WorkflowConflictError("Capture is not an exact, unrefunded payment of this order.")


async def intent_for(session: AsyncSession, order_id: UUID) -> PaymentIntent:
    intent = await session.scalar(
        select(PaymentIntent).where(PaymentIntent.order_id == order_id, PaymentIntent.version == 1)
    )
    if intent is None:
        raise WorkflowConflictError("Checkout has not been created for this order.")
    return intent


async def flag_review(session: AsyncSession, intent_id: UUID, code: str) -> None:
    await session.execute(
        update(PaymentIntent)
        .where(PaymentIntent.id == intent_id, PaymentIntent.status != "captured")
        .values(status="review", failure_code=code)
    )
    await session.execute(
        update(Order)
        .where(
            Order.id
            == select(PaymentIntent.order_id)
            .where(PaymentIntent.id == intent_id)
            .scalar_subquery(),
            Order.status.in_(PAYABLE),
        )
        .values(status="payment_review", version=Order.version + 1)
    )
    await session.commit()


async def bind_order(
    session: AsyncSession, intent: PaymentIntent, provider_order: ProviderOrder
) -> PaymentIntent:
    match_order(intent, provider_order)
    await session.execute(
        update(PaymentIntent)
        .where(
            PaymentIntent.id == intent.id,
            PaymentIntent.provider_order_id.is_(None),
        )
        .values(provider_order_id=provider_order.id, status="checkout_pending", failure_code=None)
    )
    await session.commit()
    await session.refresh(intent)
    if intent.provider_order_id != provider_order.id:
        raise WorkflowConflictError("Payment binding changed; owner investigation is required.")
    return intent


async def create_checkout(
    session: AsyncSession,
    *,
    buyer: User,
    order_id: UUID,
    settings: Settings,
    gateway: RazorpayGateway,
) -> PaymentIntent:
    order = await get_order(session, user=buyer, order_id=order_id)
    if (
        buyer.role is not Role.BUYER
        or buyer.status is not UserStatus.ACTIVE
        or buyer.email_verified_at is None
    ):
        raise WorkflowConflictError("A verified buyer account is required.")
    configured(settings)
    if order.status not in {"payment_pending", "payment_failed"}:
        raise WorkflowConflictError("This order is not awaiting payment.")
    existing = await session.scalar(select(PaymentIntent).where(PaymentIntent.order_id == order.id))
    if existing is not None:
        account_matches(existing, settings)
        if existing.provider_order_id is None or existing.status not in {
            "checkout_pending",
            "failed",
        }:
            raise WorkflowConflictError(
                "A previous Checkout needs reconciliation. Do not pay again yet."
            )
        remote = await gateway.fetch_order(existing.provider_order_id)
        match_order(existing, remote)
        attempts = await gateway.order_payments(existing.provider_order_id)
        if remote.status == "paid" or any(
            p.status in {"authorized", "captured", "refunded"} for p in attempts
        ):
            raise WorkflowConflictError(
                "A payment may already be in progress. Check payment status before retrying."
            )
        return existing
    intent_id = uuid4()
    intent = PaymentIntent(
        id=intent_id,
        order_id=order.id,
        version=1,
        provider="razorpay",
        status="created",
        currency="INR",
        amount_paise=order.amount_paise,
        payment_reference=f"pf_{intent_id.hex}",
        provider_key_id=settings.razorpay_key_id,
    )
    await compare_version(session, Order, order, order.version)
    session.add(intent)
    audit(
        session,
        AuditEventType.PAYMENT_CHECKOUT_CREATED,
        buyer,
        order.id,
        {"intent_id": str(intent_id)},
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise WorkflowConflictError(
            "Checkout is already being created. Refresh before retrying."
        ) from None
    # Durable intent first: an interrupted/uncertain POST is never automatically repeated.
    try:
        remote = await gateway.create_order(
            amount=intent.amount_paise, receipt=intent.payment_reference
        )
        return await bind_order(session, intent, remote)
    except (GatewayUnavailableError, WorkflowConflictError):
        await session.rollback()
        await flag_review(session, intent_id, "order_creation_uncertain")
        raise


async def checkout_return(
    session: AsyncSession,
    *,
    buyer: User,
    order_id: UUID,
    payment_id: str,
    provider_order_id: str,
    signature: str,
    settings: Settings,
) -> Order:
    order = await get_order(session, user=buyer, order_id=order_id)
    if buyer.role is not Role.BUYER or buyer.id != order.buyer_id:
        raise WorkflowNotFoundError
    intent = await intent_for(session, order.id)
    account_matches(intent, settings)
    secret = settings.razorpay_key_secret
    assert secret is not None
    expected = hmac.new(
        secret.get_secret_value().encode(),
        f"{intent.provider_order_id}|{payment_id}".encode(),
        "sha256",
    ).hexdigest()
    if intent.provider_order_id != provider_order_id or not hmac.compare_digest(
        expected, signature
    ):
        raise WorkflowConflictError("Checkout response could not be verified.")
    if order.status not in PAYABLE:
        return order  # A late callback cannot regress a webhook-confirmed order.
    if intent.checkout_payment_id == payment_id and order.status == "payment_processing":
        return order
    await compare_version(session, Order, order, order.version)
    intent.checkout_payment_id = payment_id
    order.status = "payment_processing"
    audit(
        session,
        AuditEventType.PAYMENT_CHECKOUT_RETURNED,
        buyer,
        order.id,
        {"intent_id": str(intent.id)},
    )
    await session.commit()
    return order


async def reconcile_intent(
    session: AsyncSession,
    *,
    intent: PaymentIntent,
    settings: Settings,
    gateway: RazorpayGateway,
    actor: User | None = None,
) -> Order:
    account_matches(intent, settings)
    intent_id = intent.id
    order = await session.get(Order, intent.order_id)
    assert order is not None
    if order.status not in PAYABLE:
        return order
    # Claim a bounded cooldown before external reads, without holding a DB transaction open.
    now = utc()
    claimed = await session.execute(
        update(PaymentIntent)
        .where(
            PaymentIntent.id == intent.id,
            or_(
                PaymentIntent.last_reconciled_at.is_(None),
                PaymentIntent.last_reconciled_at < now - timedelta(seconds=30),
            ),
        )
        .values(last_reconciled_at=now)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    if not getattr(claimed, "rowcount", 0):
        return order
    await session.refresh(intent)
    try:
        if intent.provider_order_id is None:
            matches = [
                row
                for row in await gateway.find_orders(receipt=intent.payment_reference)
                if row.receipt == intent.payment_reference
            ]
            if len(matches) != 1:
                await flag_review(session, intent.id, "receipt_unresolved")
                raise WorkflowConflictError(
                    "Checkout recovery requires owner investigation; do not pay again."
                )
            await bind_order(session, intent, matches[0])
        assert intent.provider_order_id is not None
        remote_order = await gateway.fetch_order(intent.provider_order_id)
        match_order(intent, remote_order)
        payments = await gateway.order_payments(intent.provider_order_id)
        if any(payment.order_id != intent.provider_order_id for payment in payments):
            raise WorkflowConflictError("Provider returned an unrelated payment.")
        captured = [payment for payment in payments if payment.status in {"captured", "refunded"}]
        if remote_order.status != "paid" and not captured:
            if any(p.amount != intent.amount_paise or p.currency != "INR" for p in payments):
                raise WorkflowConflictError("Provider attempt does not match the accepted amount.")
            authorized = any(p.status == "authorized" for p in payments)
            failed = any(p.status == "failed" for p in payments)
            pending_status = (
                "payment_processing"
                if authorized
                else "payment_failed"
                if failed
                else "payment_pending"
            )
            await session.execute(
                update(PaymentIntent)
                .where(PaymentIntent.id == intent.id, PaymentIntent.status != "captured")
                .values(
                    failure_code=None, status="authorized" if authorized else "checkout_pending"
                )
            )
            await session.execute(
                update(Order)
                .where(Order.id == order.id, Order.status.in_(PAYABLE))
                .values(status=pending_status, version=Order.version + 1)
            )
            await session.commit()
            await session.refresh(order)
            return order
        if len(captured) != 1:
            raise WorkflowConflictError("Provider payment state requires owner investigation.")
        payment = await gateway.fetch_payment(captured[0].id)
        if payment.id != captured[0].id:
            raise WorkflowConflictError("Provider returned an unrelated payment.")
        match_capture(intent, remote_order, payment)
        normalized = {"order": remote_order.model_dump(), "payment": payment.model_dump()}
        event = PaymentProviderEvent(
            id=uuid4(),
            provider="razorpay",
            provider_event_id=f"api_{uuid4().hex}",
            event_type="api.reconciled",
            evidence_source="api",
            api_authenticated_at=utc(),
            payload_sha256=hashlib.sha256(
                json.dumps(normalized, sort_keys=True).encode()
            ).hexdigest(),
            payment_intent_id=intent.id,
            status="received",
            received_at=utc(),
        )
        session.add(event)
        audit(
            session, AuditEventType.PAYMENT_RECONCILED, actor, order.id, {"event_id": str(event.id)}
        )
        await session.flush()
        return await record_captured_payment(
            session,
            event_id=event.id,
            intent_id=intent.id,
            provider_order_id=remote_order.id,
            provider_payment_id=payment.id,
            amount_paise=payment.amount,
            currency=payment.currency,
            captured=True,
        )
    except GatewayUnavailableError:
        await session.rollback()
        await session.execute(
            update(PaymentIntent)
            .where(PaymentIntent.id == intent_id, PaymentIntent.status != "captured")
            .values(failure_code="provider_unavailable")
        )
        await session.commit()
        raise
    except WorkflowConflictError:
        await session.rollback()
        await flag_review(session, intent_id, "reconciliation_conflict")
        raise


def _unique_json(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


async def ingest_webhook(
    session: AsyncSession,
    *,
    raw: bytes,
    signature: str,
    provider_event_id: str,
    settings: Settings,
    gateway: RazorpayGateway,
) -> PaymentProviderEvent:
    configured(settings)
    secret = settings.razorpay_webhook_secret
    assert secret is not None
    expected = hmac.new(secret.get_secret_value().encode(), raw, "sha256").hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", signature) or not hmac.compare_digest(expected, signature):
        raise WorkflowConflictError("Invalid webhook signature.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", provider_event_id) or provider_event_id.startswith(
        "api_"
    ):
        raise WorkflowConflictError("Invalid provider event ID.")
    if len(raw) > 256 * 1024:
        raise WorkflowConflictError("Webhook exceeds the safe limit.")
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_json)
        if not isinstance(payload, dict) or not isinstance(payload.get("event"), str):
            raise ValueError
        event_type = payload["event"]
        if not re.fullmatch(r"[a-z._]{1,80}", event_type):
            raise ValueError
    except (ValueError, RecursionError):
        raise WorkflowConflictError("Malformed webhook.") from None
    digest = hashlib.sha256(raw).hexdigest()
    event = await session.scalar(
        select(PaymentProviderEvent).where(
            PaymentProviderEvent.provider == "razorpay",
            PaymentProviderEvent.provider_event_id == provider_event_id,
        )
    )
    if event is not None:
        if event.payload_sha256 != digest or event.evidence_source != "webhook":
            raise WorkflowConflictError("Provider event ID was reused with different evidence.")
        if event.status in {"processed", "ignored"}:
            return event
    else:
        event = PaymentProviderEvent(
            id=uuid4(),
            provider="razorpay",
            provider_event_id=provider_event_id,
            event_type=event_type,
            payload_sha256=digest,
            evidence_source="webhook",
            signature_validated_at=utc(),
            received_at=utc(),
            status="received",
        )
        session.add(event)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            # Concurrent delivery committed first. Validate the exact body on the next pass.
            return await ingest_webhook(
                session,
                raw=raw,
                signature=signature,
                provider_event_id=provider_event_id,
                settings=settings,
                gateway=gateway,
            )
    if event_type not in {"payment.captured", "order.paid"}:
        event.status = "ignored"
        event.failure_code = "non_capture_event" if event_type in EVENTS else "unsupported_event"
        event.processed_at = utc()
        await session.commit()
        return event
    try:
        entity = payload["payload"]["payment"]["entity"]
        hinted = ProviderPayment.model_validate(entity)
    except (KeyError, TypeError, ValueError):
        event.status, event.failure_code = "failed", "malformed_capture"
        await session.commit()
        return event
    intent = await session.scalar(
        select(PaymentIntent).where(PaymentIntent.provider_order_id == hinted.order_id)
    )
    if intent is None:
        event.status, event.failure_code = "ignored", "unknown_provider_order"
        await session.commit()
        return event
    event.payment_intent_id = intent.id
    intent_id = intent.id
    event.status = "received"
    event.failure_code = None
    await session.commit()
    try:
        account_matches(intent, settings)
        remote_order = await gateway.fetch_order(hinted.order_id)
        payment = await gateway.fetch_payment(hinted.id)
        if (
            payment.id != hinted.id
            or hinted.amount != intent.amount_paise
            or hinted.currency != "INR"
            or not hinted.captured
            or hinted.status != "captured"
        ):
            raise WorkflowConflictError("Webhook does not match the stored intent.")
        match_capture(intent, remote_order, payment)
        await record_captured_payment(
            session,
            event_id=event.id,
            intent_id=intent.id,
            provider_order_id=remote_order.id,
            provider_payment_id=payment.id,
            amount_paise=payment.amount,
            currency=payment.currency,
            captured=True,
        )
        return event
    except GatewayUnavailableError:
        await session.rollback()
        await session.refresh(event)
        if event.status != "processed":
            event.failure_code = "provider_unavailable"
            await session.commit()
        raise  # 503 asks Razorpay to retry; worker reconciliation is the second recovery path.
    except WorkflowConflictError:
        await session.rollback()
        await session.refresh(event)
        if event.status != "processed":
            event.status, event.failure_code = "failed", "capture_conflict"
            await flag_review(session, intent_id, "capture_conflict")
        return event


async def reconcile_pending(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    gateway: RazorpayGateway,
    *,
    limit: int = 5,
) -> int:
    if not settings.razorpay_enabled:
        return 0
    async with sessions() as session:
        ids = list(
            await session.scalars(
                select(PaymentIntent.id)
                .join(Order)
                .where(
                    PaymentIntent.provider == "razorpay",
                    PaymentIntent.provider_key_id == settings.razorpay_key_id,
                    Order.status.in_(PAYABLE),
                    PaymentIntent.created_at < utc() - timedelta(seconds=30),
                    or_(
                        PaymentIntent.last_reconciled_at.is_(None),
                        PaymentIntent.last_reconciled_at < utc() - timedelta(minutes=2),
                    ),
                )
                .order_by(PaymentIntent.last_reconciled_at.asc(), PaymentIntent.created_at)
                .limit(limit)
            )
        )
    for intent_id in ids:
        async with sessions() as session:
            intent = await session.get(PaymentIntent, intent_id)
            assert intent is not None
            try:
                await reconcile_intent(session, intent=intent, settings=settings, gateway=gateway)
            except (GatewayUnavailableError, WorkflowConflictError):
                continue  # Bounded safe failure codes persist; do not log sensitive provider data.
    return len(ids)
