"""Outbound manual-handoff bridge. This module never sends a printer command."""

from datetime import timedelta
from hashlib import sha256
from json import dumps
from re import fullmatch
from secrets import compare_digest, token_urlsafe
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from xxx_api.domain.auth import AuditEventType
from xxx_api.models.commerce import (
    BridgeInstallation,
    Order,
    PaymentIntent,
    PrintAuthorization,
    Printer,
    PrintJob,
    PrintJobEvent,
    PrintJobItem,
    PrintReadinessCheck,
)
from xxx_api.models.identity import User
from xxx_api.schemas.commerce import DispatchEventInput
from xxx_api.services.commerce import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    audit,
    compare_version,
    manifest,
    require_owner,
    singleton_printer,
    utc,
)
from xxx_api.services.notifications import request_notice

STATION_ADAPTER = "station-zmod-v1"
DISPATCH_TRANSITIONS = {
    "claimed": {"refused", "sent"},
    "sent": {"awaiting_start", "printing", "needs_attention", "cancelled", "stopped", "completed"},
    "awaiting_start": {
        "awaiting_start",
        "printing",
        "needs_attention",
        "cancelled",
        "stopped",
        "completed",
    },
    "printing": {"printing", "completed", "needs_attention", "cancelled", "stopped"},
    "needs_attention": {"printing", "completed", "cancelled", "stopped", "resolved"},
}


def digest(raw: str) -> str:
    # Random 256-bit credentials need no password KDF and are never persisted in cleartext.
    return sha256(raw.encode()).hexdigest()


async def begin_pairing(
    session: AsyncSession, owner: User, name: str
) -> tuple[BridgeInstallation, str]:
    require_owner(owner)
    printer = await singleton_printer(session)
    if printer.active_job_id:
        raise WorkflowConflictError("Do not replace a bridge while a printer job is active.")
    bridge = await session.scalar(
        select(BridgeInstallation).where(BridgeInstallation.printer_id == printer.id)
    )
    raw = token_urlsafe(32)
    if bridge is None:
        bridge = BridgeInstallation(
            printer_id=printer.id,
            paired_by_user_id=owner.id,
            installation_name=name,
            credential_digest=digest(token_urlsafe(32)),
        )
        session.add(bridge)
    else:
        # Re-pairing immediately invalidates the previous credential and any staged handoff.
        await session.execute(
            update(PrintAuthorization)
            .where(
                PrintAuthorization.bridge_installation_id == bridge.id,
                PrintAuthorization.revoked_at.is_(None),
            )
            .values(revoked_at=utc())
        )
        bridge.credential_digest = digest(token_urlsafe(32))
    bridge.status = "pending_pairing"
    bridge.installation_name = name
    bridge.pairing_digest = digest(raw)
    bridge.pairing_expires_at = utc() + timedelta(minutes=5)
    bridge.last_heartbeat_at = None
    bridge.revoked_at = None
    bridge.paired_by_user_id = owner.id
    await session.flush()
    audit(session, AuditEventType.BRIDGE_PAIRED, owner, bridge.id, {"stage": "pairing_requested"})
    await session.commit()
    return bridge, raw


async def finish_pairing(
    session: AsyncSession, raw: str, *, adapter: str = "manual-orca"
) -> tuple[BridgeInstallation, str]:
    if adapter not in {"manual-orca", STATION_ADAPTER}:
        raise WorkflowConflictError("Unsupported bridge adapter.")
    bridge = await session.scalar(
        select(BridgeInstallation).where(BridgeInstallation.pairing_digest == digest(raw))
    )
    if (
        bridge is None
        or bridge.status != "pending_pairing"
        or bridge.pairing_expires_at is None
        or utc(bridge.pairing_expires_at) <= utc()
    ):
        raise WorkflowNotFoundError
    credential = token_urlsafe(32)
    changed = await session.scalar(
        update(BridgeInstallation)
        .where(
            BridgeInstallation.id == bridge.id,
            BridgeInstallation.status == "pending_pairing",
            BridgeInstallation.pairing_digest == digest(raw),
            BridgeInstallation.pairing_expires_at > utc(),
        )
        .values(
            status="paired",
            pairing_digest=None,
            pairing_expires_at=None,
            paired_at=utc(),
            credential_digest=digest(credential),
            adapter_name=adapter,
        )
        .returning(BridgeInstallation.id)
        .execution_options(synchronize_session="fetch")
    )
    if changed is None:
        raise WorkflowNotFoundError
    await session.commit()
    return bridge, credential


async def authenticate_bridge(session: AsyncSession, credential: str) -> BridgeInstallation:
    bridge = await session.scalar(
        select(BridgeInstallation).where(
            BridgeInstallation.credential_digest == digest(credential),
            BridgeInstallation.status == "paired",
            BridgeInstallation.revoked_at.is_(None),
        )
    )
    if bridge is None:
        raise WorkflowNotFoundError
    return bridge


async def revoke_bridge(session: AsyncSession, owner: User, bridge_id: UUID) -> None:
    require_owner(owner)
    bridge = await session.get(BridgeInstallation, bridge_id)
    if bridge is None:
        raise WorkflowNotFoundError
    bridge.status = "revoked"
    bridge.revoked_at = utc()
    bridge.pairing_digest = None
    bridge.credential_digest = digest(token_urlsafe(32))
    await session.execute(
        update(PrintAuthorization)
        .where(
            PrintAuthorization.bridge_installation_id == bridge.id,
            PrintAuthorization.revoked_at.is_(None),
        )
        .values(revoked_at=utc())
    )
    audit(session, AuditEventType.BRIDGE_REVOKED, owner, bridge.id)
    await session.commit()


async def _authorize(
    session: AsyncSession, owner: User, job_id: UUID, expected_version: int, adapter: str
) -> PrintAuthorization:
    require_owner(owner)
    job = await session.get(PrintJob, job_id)
    if job is None:
        raise WorkflowNotFoundError
    printer = await singleton_printer(session)
    bridge = await session.scalar(
        select(BridgeInstallation).where(
            BridgeInstallation.printer_id == printer.id,
            BridgeInstallation.status == "paired",
            BridgeInstallation.revoked_at.is_(None),
        )
    )
    readiness = await session.scalar(
        select(PrintReadinessCheck)
        .where(PrintReadinessCheck.print_job_id == job.id)
        .order_by(PrintReadinessCheck.completed_at.desc())
    )
    _, manifest_hash = await manifest(session, job)
    if (
        job.status != "ready_to_print"
        or printer.active_job_id != job.id
        or bridge is None
        or bridge.adapter_name != adapter
        or bridge.last_heartbeat_at is None
        or utc(bridge.last_heartbeat_at) < utc() - timedelta(seconds=60)
        or readiness is None
        or utc(readiness.completed_at) < utc() - timedelta(minutes=10)
        or readiness.manifest_sha256 != manifest_hash
    ):
        raise WorkflowConflictError(
            "Handoff requires a ready reserved job, fresh checklist and online paired bridge."
        )
    await compare_version(session, PrintJob, job, expected_version)
    await session.execute(
        update(PrintAuthorization)
        .where(
            PrintAuthorization.print_job_id == job.id,
            PrintAuthorization.consumed_at.is_(None),
            PrintAuthorization.revoked_at.is_(None),
        )
        .values(revoked_at=utc())
    )
    authorization = PrintAuthorization(
        print_job_id=job.id,
        printer_id=printer.id,
        bridge_installation_id=bridge.id,
        readiness_check_id=readiness.id,
        nonce_digest=digest(token_urlsafe(32)),
        manifest_sha256=manifest_hash,
        issued_by_user_id=owner.id,
        issued_at=utc(),
        expires_at=utc() + timedelta(minutes=2),
        result_code="station_authorized" if adapter == STATION_ADAPTER else None,
    )
    session.add(authorization)
    audit(
        session,
        AuditEventType.PRINT_AUTHORIZED,
        owner,
        job.id,
        {"adapter": adapter, "dispatch": adapter == STATION_ADAPTER},
    )
    return authorization


async def authorize_handoff(
    session: AsyncSession, owner: User, job_id: UUID, expected_version: int
) -> PrintAuthorization:
    authorization = await _authorize(session, owner, job_id, expected_version, "manual-orca")
    await session.commit()
    return authorization


async def handoff_access(
    session: AsyncSession, bridge: BridgeInstallation, authorization_id: UUID
) -> tuple[PrintAuthorization, PrintJob]:
    if bridge.adapter_name != "manual-orca":
        raise WorkflowNotFoundError
    active = await session.scalar(
        select(BridgeInstallation.id).where(
            BridgeInstallation.id == bridge.id,
            BridgeInstallation.status == "paired",
            BridgeInstallation.revoked_at.is_(None),
        )
    )
    if active is None:
        raise WorkflowNotFoundError
    authorization = await session.get(PrintAuthorization, authorization_id, populate_existing=True)
    if (
        authorization is None
        or authorization.bridge_installation_id != bridge.id
        or authorization.revoked_at is not None
        or utc(authorization.expires_at) <= utc()
    ):
        raise WorkflowNotFoundError
    job = await session.get(PrintJob, authorization.print_job_id)
    if job is None or job.status != "ready_to_print":
        raise WorkflowConflictError("The job is no longer ready for manual handoff.")
    _, current_hash = await manifest(session, job)
    if not compare_digest(current_hash, authorization.manifest_sha256):
        raise WorkflowConflictError("The approved manifest changed.")
    printer = await session.get(Printer, authorization.printer_id)
    if printer is None or printer.active_job_id != job.id:
        raise WorkflowConflictError("The printer slot is no longer reserved.")
    return authorization, job


async def _eligible_order(session: AsyncSession, job: PrintJob) -> tuple[Order, PrintJobItem]:
    order = await session.get(Order, job.order_id)
    items, _ = await manifest(session, job)
    if len(items) != 1 or items[0].quantity != 1:
        raise WorkflowConflictError(
            "Manual handoff required — automatic sending supports one file x one copy."
        )
    specification = order.print_specification if order else None
    if (
        order is None
        or order.commercial_snapshot.get("schemaVersion") != 2
        or not specification
        or not isinstance(specification.get("materialCode"), str)
        or not isinstance(specification.get("colour"), str)
        or not fullmatch(r"[0-9a-f]{64}", str(specification.get("profileSha256", "")))
    ):
        raise WorkflowConflictError("Manual handoff required — no captured print specification.")
    payment = await session.scalar(
        select(PaymentIntent.id).where(
            PaymentIntent.order_id == order.id,
            PaymentIntent.status == "captured",
            PaymentIntent.amount_paise == order.amount_paise,
            PaymentIntent.currency == order.currency,
        )
    )
    if payment is None:
        raise WorkflowConflictError("A captured payment for this exact order is required.")
    return order, items[0]


async def dispatch_status(
    session: AsyncSession, job_id: UUID, *, enabled: bool
) -> dict[str, object]:
    job = await session.get(PrintJob, job_id)
    if job is None:
        raise WorkflowNotFoundError
    reason = None
    try:
        await _eligible_order(session, job)
    except WorkflowConflictError as error:
        reason = str(error)
    bridge = await session.scalar(
        select(BridgeInstallation).where(
            BridgeInstallation.status == "paired",
            BridgeInstallation.revoked_at.is_(None),
        )
    )
    online = bool(
        bridge
        and bridge.last_heartbeat_at
        and utc(bridge.last_heartbeat_at) >= utc() - timedelta(seconds=60)
    )
    authorization = await session.scalar(
        select(PrintAuthorization)
        .where(
            PrintAuthorization.print_job_id == job.id,
            PrintAuthorization.result_code.like("station_%"),
        )
        .order_by(PrintAuthorization.issued_at.desc())
        .limit(1)
    )
    events = list(
        await session.scalars(
            select(PrintJobEvent)
            .where(
                PrintJobEvent.print_job_id == job.id,
                PrintJobEvent.event_type.like("plate_%"),
            )
            .order_by(PrintJobEvent.received_at.desc())
            .limit(25)
        )
    )
    return {
        "eligible": reason is None,
        "reason": reason,
        "enabled": enabled,
        "online": online,
        "bridgeName": bridge.installation_name if bridge else None,
        "adapter": bridge.adapter_name if bridge else None,
        "lastHeartbeatAt": utc(bridge.last_heartbeat_at).isoformat()
        if bridge and bridge.last_heartbeat_at
        else None,
        "authorization": {
            "id": str(authorization.id),
            "expiresAt": utc(authorization.expires_at).isoformat(),
            "claimedAt": utc(authorization.claimed_at).isoformat()
            if authorization.claimed_at
            else None,
            "revokedAt": utc(authorization.revoked_at).isoformat()
            if authorization.revoked_at
            else None,
        }
        if authorization
        else None,
        "events": [
            {
                "state": event.event_type.removeprefix("plate_"),
                "at": utc(event.received_at).isoformat(),
                "progressBps": event.progress_bps,
                "refusalCode": event.details.get("refusalCode"),
            }
            for event in reversed(events)
        ],
    }


async def authorize_dispatch(
    session: AsyncSession, owner: User, job_id: UUID, expected_version: int, *, enabled: bool
) -> PrintAuthorization:
    require_owner(owner)
    job = await session.get(PrintJob, job_id)
    if job is None:
        raise WorkflowNotFoundError
    if job.status == "authorized":
        unusable = await session.scalar(
            select(PrintAuthorization)
            .where(
                PrintAuthorization.print_job_id == job.id,
                PrintAuthorization.claimed_at.is_(None),
                PrintAuthorization.consumed_at.is_(None),
                PrintAuthorization.result_code == "station_authorized",
            )
            .order_by(PrintAuthorization.issued_at.desc())
            .limit(1)
        )
        if unusable and (unusable.revoked_at is not None or utc(unusable.expires_at) <= utc()):
            reason = "revoked" if unusable.revoked_at is not None else "expired"
            # Lock ordering matches claim: authorization first, then job/order CAS.
            # A racing claim wins or this reset wins; never both.
            changed = await session.scalar(
                update(PrintAuthorization)
                .where(
                    PrintAuthorization.id == unusable.id,
                    PrintAuthorization.claimed_at.is_(None),
                    PrintAuthorization.consumed_at.is_(None),
                    PrintAuthorization.result_code == "station_authorized",
                    or_(
                        PrintAuthorization.revoked_at.is_not(None),
                        PrintAuthorization.expires_at <= utc(),
                    ),
                )
                .values(
                    revoked_at=func.coalesce(PrintAuthorization.revoked_at, utc()),
                    result_code=f"station_reset_{reason}",
                )
                .returning(PrintAuthorization.id)
                .execution_options(synchronize_session="fetch")
            )
            if changed is None:
                await session.rollback()
                raise WorkflowConflictError(
                    "The station claim changed. Refresh and inspect this attempt."
                )
            order = await session.get(Order, job.order_id)
            if order is None:
                raise WorkflowNotFoundError
            await compare_version(session, PrintJob, job, expected_version)
            await compare_version(session, Order, order, order.version)
            job.status, order.status = "preparing", "preparing"
            audit(
                session,
                AuditEventType.PRINT_JOB_CHANGED,
                owner,
                job.id,
                {"action": "dispatch_reset", "reason": reason},
            )
            await request_notice(session, "buyer.order_updated", "order", order.id, order.buyer_id)
            await session.commit()
            raise WorkflowConflictError(f"authorization_reset_readiness_required: {reason}")
    if not enabled:
        raise WorkflowConflictError("Automatic printer dispatch is disabled.")
    await _eligible_order(session, job)
    previous = await session.scalar(
        select(PrintJobEvent)
        .where(
            PrintJobEvent.print_job_id == job.id,
            PrintJobEvent.event_type == "plate_refused",
        )
        .order_by(PrintJobEvent.received_at.desc())
        .limit(1)
    )
    if previous:
        fresh = await session.scalar(
            select(PrintReadinessCheck)
            .where(
                PrintReadinessCheck.print_job_id == job.id,
            )
            .order_by(PrintReadinessCheck.completed_at.desc())
            .limit(1)
        )
        if fresh is None or utc(fresh.completed_at) <= utc(previous.received_at):
            raise WorkflowConflictError("Confirm fresh printer readiness after the refused send.")
    authorization = await _authorize(session, owner, job_id, expected_version, STATION_ADAPTER)
    job.status = "authorized"
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise WorkflowConflictError("This job already has an authorization.") from error
    return authorization


async def _dispatch_context(
    session: AsyncSession, bridge: BridgeInstallation, authorization_id: UUID
) -> tuple[PrintAuthorization, PrintJob]:
    active = await session.scalar(
        select(BridgeInstallation.id).where(
            BridgeInstallation.id == bridge.id,
            BridgeInstallation.status == "paired",
            BridgeInstallation.revoked_at.is_(None),
            BridgeInstallation.adapter_name == STATION_ADAPTER,
        )
    )
    authorization = await session.get(PrintAuthorization, authorization_id, populate_existing=True)
    if (
        not active
        or authorization is None
        or authorization.bridge_installation_id != bridge.id
        or authorization.revoked_at is not None
        or not (authorization.result_code or "").startswith("station_")
    ):
        raise WorkflowNotFoundError
    job = await session.get(PrintJob, authorization.print_job_id, populate_existing=True)
    if job is None:
        raise WorkflowNotFoundError
    return authorization, job


async def _dispatch_reserved(
    session: AsyncSession, authorization: PrintAuthorization, job: PrintJob
) -> None:
    _, current = await manifest(session, job)
    printer = await session.get(Printer, authorization.printer_id, populate_existing=True)
    if (
        not compare_digest(current, authorization.manifest_sha256)
        or printer is None
        or printer.active_job_id != job.id
    ):
        raise WorkflowConflictError("The approved artifact or reserved printer changed.")


async def claim_dispatch(
    session: AsyncSession, bridge: BridgeInstallation, authorization_id: UUID, *, enabled: bool
) -> dict[str, object]:
    if not enabled:
        raise WorkflowNotFoundError
    authorization, job = await _dispatch_context(session, bridge, authorization_id)
    if authorization.claimed_at is None:
        if utc(authorization.expires_at) <= utc():
            raise WorkflowNotFoundError
        if job.status != "authorized":
            raise WorkflowConflictError("The job is not authorized for the station.")
        await _dispatch_reserved(session, authorization, job)
        changed = await session.scalar(
            update(PrintAuthorization)
            .where(
                PrintAuthorization.id == authorization.id,
                PrintAuthorization.claimed_at.is_(None),
                PrintAuthorization.consumed_at.is_(None),
                PrintAuthorization.result_code == "station_authorized",
                PrintAuthorization.revoked_at.is_(None),
                PrintAuthorization.expires_at > utc(),
            )
            .values(claimed_at=utc(), consumed_at=utc(), result_code="station_claimed")
            .returning(PrintAuthorization.id)
            .execution_options(synchronize_session="fetch")
        )
        if changed is None:
            await session.rollback()
            raise WorkflowConflictError("The authorization changed during claim.")
        await compare_version(session, PrintJob, job, job.version)
        job.status = "claimed"
        await session.commit()
    order, item = await _eligible_order(session, job)
    return {
        "jobId": str(job.id),
        "itemId": str(item.id),
        "artifactSha256": item.artifact_sha256,
        "manifestSha256": authorization.manifest_sha256,
        "downloadUrl": f"/api/v1/bridge/dispatches/{authorization.id}/artifact",
        "specification": order.print_specification,
        "claimedAt": utc(authorization.claimed_at).isoformat(),
    }


async def dispatch_artifact_access(
    session: AsyncSession, bridge: BridgeInstallation, authorization_id: UUID, *, enabled: bool
) -> tuple[PrintAuthorization, PrintJob]:
    if not enabled:
        raise WorkflowNotFoundError
    authorization, job = await _dispatch_context(session, bridge, authorization_id)
    sent = await session.scalar(
        select(PrintJobEvent.id).where(
            PrintJobEvent.print_job_id == job.id,
            PrintJobEvent.event_type == "plate_sent",
        )
    )
    if (
        job.status != "claimed"
        or authorization.claimed_at is None
        or sent
        or utc(authorization.claimed_at) < utc() - timedelta(minutes=10)
    ):
        raise WorkflowConflictError("Artifact access is only available before this exact send.")
    await _dispatch_reserved(session, authorization, job)
    return authorization, job


async def record_dispatch_event(
    session: AsyncSession,
    bridge: BridgeInstallation,
    authorization_id: UUID,
    payload: dict[str, object],
    *,
    enabled: bool,
) -> PrintJob:
    data = DispatchEventInput.model_validate(payload)
    body = data.model_dump(mode="json", by_alias=True)
    fingerprint = sha256(dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    authorization, job = await _dispatch_context(session, bridge, authorization_id)
    old = await session.scalar(
        select(PrintJobEvent).where(
            PrintJobEvent.print_job_id == job.id,
            PrintJobEvent.source_event_id == data.source_event_id,
        )
    )
    if old:
        if (
            old.bridge_installation_id != bridge.id
            or old.details.get("authorizationId") != str(authorization_id)
            or old.details.get("payloadSha256") != fingerprint
        ):
            raise WorkflowConflictError("This event ID was already used with different content.")
        return job
    if authorization.claimed_at is None or job.status not in {"claimed", "printing"}:
        raise WorkflowConflictError("The job is no longer controlled by this dispatch.")
    await _dispatch_reserved(session, authorization, job)
    events = list(
        await session.scalars(
            select(PrintJobEvent)
            .where(
                PrintJobEvent.print_job_id == job.id,
                PrintJobEvent.event_type.like("plate_%"),
            )
            .order_by(PrintJobEvent.received_at)
        )
    )
    events = [row for row in events if row.details.get("authorizationId") == str(authorization_id)]
    state = events[-1].event_type.removeprefix("plate_") if events else "claimed"
    if data.state not in DISPATCH_TRANSITIONS.get(state, set()):
        raise WorkflowConflictError("This station transition is not permitted.")
    sent = next((row for row in events if row.event_type == "plate_sent"), None)
    if data.state == "sent":
        readiness = await session.get(PrintReadinessCheck, authorization.readiness_check_id)
        if (
            not enabled
            or not data.printer_filename
            or not data.dispatch_sha256
            or utc(authorization.claimed_at) < utc() - timedelta(minutes=10)
            or readiness is None
            or utc(readiness.completed_at) < utc() - timedelta(minutes=10)
            or readiness.manifest_sha256 != authorization.manifest_sha256
        ):
            raise WorkflowConflictError(
                "Fresh dispatch authority and artifact binding are required."
            )
    elif data.state != "refused" and (
        sent is None
        or data.printer_filename != sent.details.get("printerFilename")
        or data.dispatch_sha256 != sent.details.get("dispatchSha256")
    ):
        raise WorkflowConflictError("Station status does not match the exact dispatched file.")
    if data.state == "printing":
        previous = max(
            (
                row.progress_bps // 1000
                for row in events
                if row.event_type == "plate_printing" and row.progress_bps is not None
            ),
            default=-1,
        )
        if data.progress_bps is None or data.progress_bps // 1000 <= previous:
            raise WorkflowConflictError(
                "Printing progress must advance to a new observation bucket."
            )
    order = await session.get(Order, job.order_id)
    assert order is not None
    await compare_version(session, PrintJob, job, job.version)
    if data.state in {"refused", "printing", "completed"}:
        await compare_version(session, Order, order, order.version)
        if data.state == "refused":
            job.status, order.status = "preparing", "preparing"
            authorization.result_code = "station_refused"
        elif data.state == "printing":
            job.status, order.status = "printing", "printing"
            job.started_at = job.started_at or utc()
        else:
            job.status, order.status = "qa", "qa"
            authorization.result_code = "station_completed"
            await session.execute(
                update(Printer).where(Printer.active_job_id == job.id).values(active_job_id=None)
            )
        await request_notice(session, "buyer.order_updated", "order", order.id, order.buyer_id)
    session.add(
        PrintJobEvent(
            print_job_id=job.id,
            event_type=f"plate_{data.state}",
            source_event_id=data.source_event_id,
            bridge_installation_id=bridge.id,
            progress_bps=data.progress_bps,
            observed_at=utc(data.observed_at),
            received_at=utc(),
            details={
                "authorizationId": str(authorization_id),
                "payloadSha256": fingerprint,
                "printerFilename": data.printer_filename,
                "dispatchSha256": data.dispatch_sha256,
                "refusalCode": data.refusal_code,
            },
        )
    )
    audit(
        session,
        AuditEventType.PRINT_JOB_CHANGED,
        None,
        job.id,
        {"action": f"plate_{data.state}", "bridge_id": str(bridge.id)},
    )
    await session.commit()
    return job
