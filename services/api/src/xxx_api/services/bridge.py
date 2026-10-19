"""Outbound manual-handoff bridge. This module never sends a printer command."""

from datetime import timedelta
from hashlib import sha256
from secrets import compare_digest, token_urlsafe
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from xxx_api.domain.auth import AuditEventType
from xxx_api.models.commerce import (
    BridgeInstallation,
    PrintAuthorization,
    Printer,
    PrintJob,
    PrintReadinessCheck,
)
from xxx_api.models.identity import User
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


async def finish_pairing(session: AsyncSession, raw: str) -> tuple[BridgeInstallation, str]:
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


async def authorize_handoff(
    session: AsyncSession, owner: User, job_id: UUID, expected_version: int
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
    )
    session.add(authorization)
    audit(
        session,
        AuditEventType.PRINT_AUTHORIZED,
        owner,
        job.id,
        {"adapter": "manual-orca", "dispatch": False},
    )
    await session.commit()
    return authorization


async def handoff_access(
    session: AsyncSession, bridge: BridgeInstallation, authorization_id: UUID
) -> tuple[PrintAuthorization, PrintJob]:
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
