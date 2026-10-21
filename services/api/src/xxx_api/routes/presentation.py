"""Authenticated free presentation queue and credential-scoped local dispatch."""

from hashlib import file_digest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from starlette.background import BackgroundTask

from xxx_api.config import Settings
from xxx_api.dependencies import (
    BuyerPrincipal,
    CurrentPrincipal,
    DatabaseSession,
    OwnerPrincipal,
    RecentMfaOwnerPrincipal,
    SessionCsrf,
    get_object_storage,
    get_runtime_settings,
    require_trusted_origin,
)
from xxx_api.models.presentation import PresentationEntry
from xxx_api.print_presets import load_print_presets, read_profile_bundle
from xxx_api.routes.bridge import BridgePrincipal, bridge_limit
from xxx_api.routes.commerce import enforce_workflow_limit, no_store
from xxx_api.schemas.commerce import DispatchEventInput, ReadinessInput, RejectInput, VersionInput
from xxx_api.services import presentation as service
from xxx_api.services.commerce import WorkflowConflictError, WorkflowNotFoundError
from xxx_api.storage import ObjectStorage

Runtime = Annotated[Settings, Depends(get_runtime_settings)]
Origin = Annotated[None, Depends(require_trusted_origin)]


def enabled(settings: Runtime) -> None:
    if not settings.presentation_mode:
        raise HTTPException(404, "Presentation mode is not enabled")


router = APIRouter(
    prefix="/presentation",
    tags=["free presentation"],
    dependencies=[Depends(enabled), Depends(no_store), Depends(enforce_workflow_limit)],
)
bridge_router = APIRouter(
    prefix="/bridge/presentation",
    tags=["presentation station"],
    dependencies=[Depends(enabled), Depends(no_store), Depends(bridge_limit)],
)


class SubmitInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    request_id: UUID = Field(alias="requestId")
    estimate_id: UUID = Field(alias="estimateId")
    expected_version: int = Field(alias="expectedVersion", strict=True, ge=1)


class HeartbeatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["ready", "busy", "offline"]


@router.get("/entries")
async def entries(principal: CurrentPrincipal, session: DatabaseSession) -> dict[str, Any]:
    query = select(PresentationEntry)
    owner = principal.user.role == "owner"
    if not owner:
        query = query.where(PresentationEntry.buyer_id == principal.user.id)
    rows = list(
        await session.scalars(query.order_by(PresentationEntry.created_at.desc()).limit(100))
    )
    station = await service.station(session)
    first = await service.head(session) if owner else None
    grants = await service.grants(session) if owner else []
    return {
        "items": [await service.public_entry(session, row) for row in rows],
        "free": True,
        "station": {
            "state": station.state if service.online(station) else "offline",
            "activeEntryId": str(station.active_entry_id)
            if owner and station.active_entry_id
            else None,
            "nextEntryId": str(first.id) if first else None,
            "clearedEntryId": grants[0]["id"] if grants else None,
        },
    }


@router.post("/entries", status_code=201)
async def submit(
    payload: SubmitInput,
    buyer: BuyerPrincipal,
    session: DatabaseSession,
    _origin: Origin,
    _csrf: SessionCsrf,
) -> dict[str, Any]:
    row = await service.submit(
        session, buyer.user, payload.request_id, payload.estimate_id, payload.expected_version
    )
    return await service.public_entry(session, row)


@router.post("/entries/{identifier}/admit")
async def admit(
    identifier: UUID,
    payload: VersionInput,
    owner: OwnerPrincipal,
    session: DatabaseSession,
    _origin: Origin,
    _csrf: SessionCsrf,
) -> dict[str, Any]:
    row = await service.entry(session, identifier)
    row = await service.admit(session, owner.user, row, payload.expected_version)
    return await service.public_entry(session, row)


@router.post("/entries/{identifier}/reject")
async def reject(
    identifier: UUID,
    payload: RejectInput,
    owner: OwnerPrincipal,
    session: DatabaseSession,
    _origin: Origin,
    _csrf: SessionCsrf,
) -> dict[str, Any]:
    row = await service.entry(session, identifier)
    row = await service.admit(
        session, owner.user, row, payload.expected_version, reject_reason=payload.reason
    )
    return await service.public_entry(session, row)


@router.post("/entries/{identifier}/clearance")
async def clearance(
    identifier: UUID,
    payload: ReadinessInput,
    owner: RecentMfaOwnerPrincipal,
    session: DatabaseSession,
    _origin: Origin,
    _csrf: SessionCsrf,
) -> dict[str, str]:
    await service.clear_bed(session, owner.user, await service.entry(session, identifier), payload)
    return {
        "message": "Single-use clearance saved. The service will send this model once when ready."
    }


@bridge_router.post("/heartbeat")
async def heartbeat(
    payload: HeartbeatInput, bridge: BridgePrincipal, session: DatabaseSession
) -> dict[str, str]:
    await service.heartbeat(session, bridge, payload.state)
    return {"status": "ok"}


@bridge_router.get("/dispatches")
async def grants(bridge: BridgePrincipal, session: DatabaseSession) -> dict[str, Any]:
    service.require_station(bridge)
    return {"items": await service.grants(session)}


@bridge_router.post("/dispatches/{identifier}/claim")
async def claim(
    identifier: UUID, bridge: BridgePrincipal, session: DatabaseSession, settings: Runtime
) -> dict[str, Any]:
    row = await service.claim(session, bridge, identifier)
    request, _estimate, result, _asset = await service.artifact(session, row)
    specification = request.print_specification
    assert specification is not None
    preset = next(
        (
            item
            for item in load_print_presets(settings)
            if item.code == specification["presetCode"]
            and item.profile_sha256 == specification["profileSha256"]
        ),
        None,
    )
    if preset is None:
        raise WorkflowConflictError("The captured print profile is no longer available.")
    return {
        "jobId": str(row.id),
        "itemId": str(result.id),
        "artifactSha256": result.artifact_sha256,
        "downloadUrl": f"/api/v1/bridge/presentation/dispatches/{identifier}/artifact",
        "specification": specification,
        "profile": {
            name: data.decode("utf-8")
            for name, data in read_profile_bundle(
                preset.profile_directory, preset.profile_sha256
            ).items()
        },
    }


@bridge_router.get("/dispatches/{identifier}/artifact")
async def artifact(
    identifier: UUID,
    bridge: BridgePrincipal,
    session: DatabaseSession,
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> FileResponse:
    row = await service.entry(session, identifier)
    if row.status != "claimed" or row.bridge_id != bridge.id:
        raise WorkflowNotFoundError
    _request, _estimate, result, _asset = await service.artifact(session, row)
    assert result.artifact_storage_key is not None
    scratch = TemporaryDirectory(prefix="presentation-artifact-")
    target = Path(scratch.name) / "approved.gcode"
    try:
        await storage.download_to_path(
            result.artifact_storage_key, target, max_bytes=200 * 1024 * 1024
        )
        with target.open("rb") as stream:
            if file_digest(stream, "sha256").hexdigest() != result.artifact_sha256:
                raise WorkflowConflictError(
                    "The stored slicing artifact failed its integrity check."
                )
    except Exception:
        scratch.cleanup()
        raise
    return FileResponse(
        target,
        media_type="application/octet-stream",
        filename="approved.gcode",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        background=BackgroundTask(scratch.cleanup),
    )


@bridge_router.post("/dispatches/{identifier}/events")
async def event(
    identifier: UUID, payload: DispatchEventInput, bridge: BridgePrincipal, session: DatabaseSession
) -> dict[str, str]:
    row = await service.record_event(
        session, bridge, await service.entry(session, identifier), payload
    )
    return {"status": row.status}
