"""Measured estimates -> explicit free submission -> owner admission -> one-shot dispatch."""

from datetime import timedelta
from hashlib import sha256
from json import dumps
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from xxx_api.domain.auth import AuditEventType
from xxx_api.domain.quotes import AnalysisAssetStatus, AnalysisRunStatus, ModelAssetStatus
from xxx_api.models.analysis import AnalysisAssetResult, AnalysisRun
from xxx_api.models.commerce import BridgeInstallation
from xxx_api.models.identity import User
from xxx_api.models.presentation import PresentationEntry, PresentationStation
from xxx_api.models.pricing import QuoteEstimate
from xxx_api.models.quotes import ModelAsset, QuoteRequest
from xxx_api.schemas.commerce import DispatchEventInput, ReadinessInput
from xxx_api.services.commerce import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    audit,
    require_owner,
    utc,
)

TERMINAL = {"completed", "rejected", "cancelled", "stopped", "refused"}


async def entry(
    session: AsyncSession, identifier: UUID, user: User | None = None
) -> PresentationEntry:
    row = await session.get(PresentationEntry, identifier, populate_existing=True)
    if row is None or (user and user.role != "owner" and row.buyer_id != user.id):
        raise WorkflowNotFoundError
    return row


async def station(session: AsyncSession) -> PresentationStation:
    row = await session.get(PresentationStation, 1, populate_existing=True)
    if row is None:
        raise WorkflowConflictError("Initialize the presentation queue migration first.")
    return row


def online(row: PresentationStation) -> bool:
    return bool(row.heartbeat_at and utc(row.heartbeat_at) > utc() - timedelta(seconds=30))


async def artifact(
    session: AsyncSession, row: PresentationEntry
) -> tuple[QuoteRequest, QuoteEstimate, AnalysisAssetResult, ModelAsset]:
    request = await session.get(QuoteRequest, row.quote_request_id)
    estimate = await session.get(QuoteEstimate, row.estimate_id)
    analysis = await session.get(AnalysisRun, estimate.analysis_run_id) if estimate else None
    assets = list(
        await session.scalars(
            select(ModelAsset).where(ModelAsset.quote_request_id == row.quote_request_id)
        )
    )
    result = (
        await session.scalar(
            select(AnalysisAssetResult).where(AnalysisAssetResult.analysis_run_id == analysis.id)
        )
        if analysis
        else None
    )
    if (
        not request
        or not estimate
        or not analysis
        or not result
        or request.buyer_id != row.buyer_id
        or estimate.quote_request_id != request.id
        or request.quantity != 1
        or len(assets) != 1
        or assets[0].declared_format not in {"stl", "obj"}
        or assets[0].status != ModelAssetStatus.VALIDATED
        or result.model_asset_id != assets[0].id
        or result.status != AnalysisAssetStatus.SLICED
        or result.verified_sha256 != assets[0].verified_sha256
        or analysis.quote_request_id != request.id
        or analysis.status != AnalysisRunStatus.SUCCEEDED
        or estimate.quote_request_version != request.version
        or not request.print_specification
        or analysis.profile_sha256 != request.print_specification.get("profileSha256")
        or analysis.print_preset_code != request.print_specification.get("presetCode")
        or analysis.material_code != request.print_specification.get("materialCode")
        or estimate.material_code != analysis.material_code
        or estimate.filament_mg != result.filament_mg
        or estimate.duration_seconds != result.duration_seconds
        or result.fits_build_volume is not True
        or not result.artifact_storage_key
        or not result.artifact_sha256
    ):
        raise WorkflowConflictError(
            "Automatic presentation printing needs one validated STL/OBJ, one copy "
            "and a matching completed slice."
        )
    return request, estimate, result, assets[0]


async def submit(
    session: AsyncSession, buyer: User, request_id: UUID, estimate_id: UUID, expected_version: int
) -> PresentationEntry:
    if buyer.role != "buyer":
        raise WorkflowConflictError("Only buyers submit models to the waiting list.")
    request = await session.get(QuoteRequest, request_id)
    estimate = await session.get(QuoteEstimate, estimate_id)
    if not request or request.buyer_id != buyer.id:
        raise WorkflowNotFoundError
    old = await session.scalar(
        select(PresentationEntry).where(PresentationEntry.quote_request_id == request_id)
    )
    if old:
        if old.estimate_id != estimate_id:
            raise WorkflowConflictError("This request already has a different queue submission.")
        return old
    if request.version != expected_version or not estimate or utc(estimate.expires_at) <= utc():
        raise WorkflowConflictError("Refresh your measured estimate before submitting.")
    row = PresentationEntry(
        id=uuid4(),
        quote_request_id=request_id,
        estimate_id=estimate_id,
        buyer_id=buyer.id,
        status="waiting",
        version=1,
        events=[],
    )
    await artifact(session, row)
    session.add(row)
    audit(
        session,
        AuditEventType.PRINT_JOB_CHANGED,
        buyer,
        row.id,
        {"presentation": True, "action": "submitted_free"},
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        old = await session.scalar(
            select(PresentationEntry).where(PresentationEntry.quote_request_id == request_id)
        )
        if not old or old.estimate_id != estimate_id:
            raise WorkflowConflictError("The queue submission changed. Refresh.") from None
        return cast(PresentationEntry, old)
    return row


async def admit(
    session: AsyncSession,
    owner: User,
    row: PresentationEntry,
    version: int,
    *,
    reject_reason: str | None = None,
) -> PresentationEntry:
    require_owner(owner)
    if row.version != version or row.status != "waiting":
        raise WorkflowConflictError("This waiting-list entry changed. Refresh.")
    if reject_reason is None:
        await artifact(session, row)
    changed = await session.scalar(
        update(PresentationEntry)
        .where(
            PresentationEntry.id == row.id,
            PresentationEntry.version == version,
            PresentationEntry.status == "waiting",
        )
        .values(
            version=version + 1,
            status="rejected" if reject_reason else "approved",
            approved_by=owner.id,
            approved_at=utc(),
            reason=reject_reason,
        )
        .returning(PresentationEntry.id)
    )
    if not changed:
        await session.rollback()
        raise WorkflowConflictError("The admission was already handled.")
    audit(
        session,
        AuditEventType.PRINT_JOB_CHANGED,
        owner,
        row.id,
        {"presentation": True, "action": "rejected" if reject_reason else "admitted_free"},
    )
    await session.commit()
    return await entry(session, row.id)


async def head(session: AsyncSession) -> PresentationEntry | None:
    return cast(
        PresentationEntry | None,
        await session.scalar(
            select(PresentationEntry)
            .where(PresentationEntry.status == "approved")
            .order_by(PresentationEntry.approved_at, PresentationEntry.id)
            .limit(1)
        ),
    )


async def clear_bed(
    session: AsyncSession, owner: User, row: PresentationEntry, payload: ReadinessInput
) -> None:
    require_owner(owner)
    state = await station(session)
    first = await head(session)
    if (
        not first
        or first.id != row.id
        or row.version != payload.expected_version
        or state.active_entry_id
        or not online(state)
        or state.state != "ready"
    ):
        raise WorkflowConflictError(
            "Clearance is only available for the next queued model "
            "while the connected printer is ready."
        )
    if not all(
        [
            payload.bed_clear,
            payload.material_loaded,
            payload.nozzle_checked,
            payload.area_clear,
            payload.artifact_reviewed,
        ]
    ):
        raise WorkflowConflictError(
            "Confirm the clear installed plate, material/nozzle, settings and supervision."
        )
    changed = await session.scalar(
        update(PresentationStation)
        .where(
            PresentationStation.id == 1,
            PresentationStation.version == state.version,
            PresentationStation.active_entry_id.is_(None),
        )
        .values(version=state.version + 1, clear_entry_id=row.id, cleared_at=utc())
        .returning(PresentationStation.id)
    )
    if not changed:
        await session.rollback()
        raise WorkflowConflictError("Printer readiness changed. Refresh.")
    audit(
        session,
        AuditEventType.PRINT_READINESS_COMPLETED,
        owner,
        row.id,
        {"presentation": True, "action": "next_plate_clear"},
    )
    await session.commit()


async def heartbeat(session: AsyncSession, bridge: BridgeInstallation, observed: str) -> None:
    require_station(bridge)
    # Heartbeats do not modify the reservation/clearance version.
    await session.execute(
        update(PresentationStation)
        .where(PresentationStation.id == 1)
        .values(state=observed, heartbeat_at=utc())
    )
    bridge.last_heartbeat_at = utc()
    await session.commit()


async def grants(session: AsyncSession) -> list[dict[str, str]]:
    state = await station(session)
    first = await head(session)
    if (
        state.active_entry_id
        or not first
        or not online(state)
        or state.state != "ready"
        or state.clear_entry_id != first.id
        or not state.cleared_at
        or utc(state.cleared_at) < utc() - timedelta(minutes=5)
    ):
        return []
    return [{"id": str(first.id), "jobId": str(first.id)}]


def require_station(bridge: BridgeInstallation) -> None:
    if bridge.adapter_name != "station-zmod-v1":
        raise WorkflowNotFoundError


async def claim(
    session: AsyncSession, bridge: BridgeInstallation, identifier: UUID
) -> PresentationEntry:
    require_station(bridge)
    row = await entry(session, identifier)
    if row.status == "approved":
        if not any(item["id"] == str(identifier) for item in await grants(session)):
            raise WorkflowConflictError("This job has no current single-use bed clearance.")
        state = await station(session)
        changed = await session.scalar(
            update(PresentationStation)
            .where(
                PresentationStation.id == 1,
                PresentationStation.version == state.version,
                PresentationStation.active_entry_id.is_(None),
                PresentationStation.clear_entry_id == identifier,
            )
            .values(
                version=state.version + 1,
                active_entry_id=identifier,
                clear_entry_id=None,
                cleared_at=None,
            )
            .returning(PresentationStation.id)
        )
        changed_entry = (
            await session.scalar(
                update(PresentationEntry)
                .where(
                    PresentationEntry.id == identifier,
                    PresentationEntry.status == "approved",
                    PresentationEntry.version == row.version,
                )
                .values(
                    version=row.version + 1,
                    status="claimed",
                    claimed_at=utc(),
                    bridge_id=bridge.id,
                    authorization_id=identifier,
                )
                .returning(PresentationEntry.id)
            )
            if changed
            else None
        )
        if not changed or not changed_entry:
            await session.rollback()
            raise WorkflowConflictError("This queue position was already claimed.")
        await session.commit()
        row = await entry(session, identifier)
    if row.status != "claimed" or row.bridge_id != bridge.id:
        raise WorkflowConflictError("This exact station claim is no longer available.")
    await artifact(session, row)
    return row


async def record_event(
    session: AsyncSession,
    bridge: BridgeInstallation,
    row: PresentationEntry,
    payload: DispatchEventInput,
) -> PresentationEntry:
    require_station(bridge)
    if row.bridge_id != bridge.id or not row.claimed_at:
        raise WorkflowNotFoundError
    body = payload.model_dump(mode="json", by_alias=True)
    fingerprint = sha256(dumps(body, sort_keys=True).encode()).hexdigest()
    old = next((event for event in row.events if event["id"] == payload.source_event_id), None)
    if old:
        if old["fingerprint"] != fingerprint:
            raise WorkflowConflictError("This event ID was used with different content.")
        return row
    if row.status in TERMINAL or len(row.events) >= 100:
        raise WorkflowConflictError("This attempt is already terminal or needs inspection.")
    state = await station(session)
    if state.active_entry_id != row.id:
        raise WorkflowConflictError("This attempt no longer owns the printer reservation.")
    states = {
        "sent": "starting",
        "awaiting_start": "starting",
        "printing": "printing",
        "completed": "completed",
        "cancelled": "cancelled",
        "stopped": "stopped",
        "refused": "refused",
        "needs_attention": "needs_attention",
        "resolved": "stopped",
    }
    if payload.state not in states:
        raise WorkflowConflictError("Unsupported presentation observation.")
    allowed = {
        "claimed": {"sent", "refused"},
        "starting": {
            "awaiting_start",
            "printing",
            "completed",
            "cancelled",
            "stopped",
            "needs_attention",
        },
        "printing": {"printing", "completed", "cancelled", "stopped", "needs_attention"},
        "needs_attention": {
            "needs_attention",
            "printing",
            "completed",
            "cancelled",
            "stopped",
            "resolved",
        },
    }
    if payload.state not in allowed.get(row.status, set()):
        raise WorkflowConflictError("Observation would regress or skip this physical attempt.")
    if payload.state != "refused" and (not payload.printer_filename or not payload.dispatch_sha256):
        raise WorkflowConflictError(
            "Physical observations require the exact filename and wire hash."
        )
    if row.printer_filename and (
        row.printer_filename != payload.printer_filename
        or row.dispatch_sha256 != payload.dispatch_sha256
    ):
        raise WorkflowConflictError("Observation does not match the sent artifact.")
    values: dict[str, Any] = {
        "status": states[payload.state],
        "version": row.version + 1,
        "events": [
            *row.events,
            {
                "id": payload.source_event_id,
                "fingerprint": fingerprint,
                "state": payload.state,
                "at": payload.observed_at.isoformat(),
            },
        ],
        "reason": payload.refusal_code,
        "progress_bps": payload.progress_bps or row.progress_bps,
    }
    if payload.printer_filename:
        values.update(
            printer_filename=payload.printer_filename, dispatch_sha256=payload.dispatch_sha256
        )
    if states[payload.state] in TERMINAL:
        values["completed_at"] = utc()
        await session.execute(
            update(PresentationStation)
            .where(PresentationStation.id == 1, PresentationStation.active_entry_id == row.id)
            .values(
                version=state.version + 1,
                active_entry_id=None,
                clear_entry_id=None,
                cleared_at=None,
            )
        )
    changed = await session.scalar(
        update(PresentationEntry)
        .where(
            PresentationEntry.id == row.id,
            PresentationEntry.version == row.version,
        )
        .values(**values)
        .returning(PresentationEntry.id)
    )
    if not changed:
        await session.rollback()
        raise WorkflowConflictError("Another observation updated this attempt.")
    await session.commit()
    return await entry(session, row.id)


async def public_entry(session: AsyncSession, row: PresentationEntry) -> dict[str, Any]:
    request = await session.get(QuoteRequest, row.quote_request_id)
    estimate = await session.get(QuoteEstimate, row.estimate_id)
    filenames = list(
        await session.scalars(
            select(ModelAsset.original_filename).where(
                ModelAsset.quote_request_id == row.quote_request_id
            )
        )
    )
    if request is None or estimate is None:
        raise WorkflowNotFoundError
    return {
        "id": str(row.id),
        "requestId": str(row.quote_request_id),
        "status": row.status,
        "version": row.version,
        "filenames": filenames,
        "referenceCostPaise": estimate.total_paise,
        "durationSeconds": estimate.duration_seconds,
        "specification": request.print_specification,
        "submittedAt": row.created_at.isoformat(),
        "approvedAt": row.approved_at.isoformat() if row.approved_at else None,
        "progressBps": row.progress_bps,
        "reason": row.reason,
        "free": True,
    }
