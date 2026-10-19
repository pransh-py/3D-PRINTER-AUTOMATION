"""MFA-protected pairing and credential-scoped outbound artifact handoff."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update

from xxx_api.dependencies import (
    DatabaseSession,
    OwnerPrincipal,
    RecentMfaOwnerPrincipal,
    SessionCsrf,
    get_rate_limiter,
)
from xxx_api.models.commerce import BridgeInstallation, PrintAuthorization, PrintJobItem
from xxx_api.rate_limit import (
    RateLimiter,
    RateLimitExceededError,
    RateLimitRule,
    RateLimitUnavailableError,
)
from xxx_api.routes.commerce import Storage, TrustedOrigin, artifact_response
from xxx_api.schemas.commerce import VersionInput
from xxx_api.services.bridge import (
    authenticate_bridge,
    authorize_handoff,
    begin_pairing,
    finish_pairing,
    handoff_access,
    revoke_bridge,
)
from xxx_api.services.commerce import WorkflowNotFoundError, manifest, utc


class PairInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=40, max_length=128)


class NameInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")


async def bridge_limit(
    request: Request, limiter: Annotated[RateLimiter, Depends(get_rate_limiter)]
) -> None:
    try:
        await limiter.enforce(
            "bridge",
            (RateLimitRule(request.client.host if request.client else "unknown", 120, 60),),
        )
    except RateLimitExceededError as error:
        raise HTTPException(
            429, "Too many bridge requests", headers={"Retry-After": str(error.retry_after_seconds)}
        ) from error
    except RateLimitUnavailableError as error:
        raise HTTPException(503, "Bridge protection is temporarily unavailable") from error


router = APIRouter(tags=["manual bridge"], dependencies=[Depends(bridge_limit)])


async def bridge_principal(
    session: DatabaseSession, authorization: Annotated[str | None, Header()] = None
) -> BridgeInstallation:
    if (
        not authorization
        or not authorization.startswith("Bearer ")
        or not 40 <= len(authorization[7:]) <= 128
    ):
        raise HTTPException(401, "Invalid bridge credential")
    try:
        return await authenticate_bridge(session, authorization[7:])
    except WorkflowNotFoundError as error:
        raise HTTPException(401, "Invalid bridge credential") from error


BridgePrincipal = Annotated[BridgeInstallation, Depends(bridge_principal)]


@router.get("/owner/bridges")
async def bridges(_owner: OwnerPrincipal, session: DatabaseSession) -> dict[str, object]:
    rows = await session.scalars(select(BridgeInstallation))
    return {
        "items": [
            {
                "id": row.id,
                "name": row.installation_name,
                "status": row.status,
                "lastHeartbeatAt": utc(row.last_heartbeat_at).isoformat()
                if row.last_heartbeat_at
                else None,
                "adapter": "manual-orca",
            }
            for row in rows
        ]
    }


@router.post("/owner/bridges/pairing")
async def pairing(
    payload: NameInput,
    _origin: TrustedOrigin,
    _csrf: SessionCsrf,
    owner: RecentMfaOwnerPrincipal,
    session: DatabaseSession,
) -> dict[str, object]:
    bridge, token = await begin_pairing(session, owner.user, payload.name)
    return {"id": bridge.id, "pairingToken": token, "expiresAt": bridge.pairing_expires_at}


@router.post("/owner/bridges/{bridge_id}/revoke", status_code=204)
async def revoke(
    bridge_id: UUID,
    _origin: TrustedOrigin,
    _csrf: SessionCsrf,
    owner: RecentMfaOwnerPrincipal,
    session: DatabaseSession,
) -> None:
    await revoke_bridge(session, owner.user, bridge_id)


@router.post("/owner/production/{job_id}/handoff")
async def authorize(
    job_id: UUID,
    payload: VersionInput,
    _origin: TrustedOrigin,
    _csrf: SessionCsrf,
    owner: RecentMfaOwnerPrincipal,
    session: DatabaseSession,
) -> dict[str, object]:
    row = await authorize_handoff(session, owner.user, job_id, payload.expected_version)
    return {"id": row.id, "expiresAt": row.expires_at, "dispatchEnabled": False}


@router.post("/bridge/pair")
async def pair(payload: PairInput, session: DatabaseSession) -> dict[str, object]:
    row, credential = await finish_pairing(session, payload.token)
    return {
        "id": row.id,
        "credential": credential,
        "adapter": "manual-orca",
        "dispatchEnabled": False,
    }


@router.post("/bridge/heartbeat")
async def heartbeat(bridge: BridgePrincipal, session: DatabaseSession) -> dict[str, object]:
    bridge.last_heartbeat_at = utc()
    await session.commit()
    # Connectivity is not proof that a physical printer is idle; no printer state is inferred.
    return {"adapter": "manual-orca", "dispatchEnabled": False}


@router.get("/bridge/handoffs")
async def handoffs(bridge: BridgePrincipal, session: DatabaseSession) -> dict[str, object]:
    rows = await session.scalars(
        select(PrintAuthorization).where(
            PrintAuthorization.bridge_installation_id == bridge.id,
            PrintAuthorization.revoked_at.is_(None),
            PrintAuthorization.consumed_at.is_(None),
            PrintAuthorization.expires_at > utc(),
        )
    )
    return {
        "items": [
            {
                "id": row.id,
                "jobId": row.print_job_id,
                "manifestSha256": row.manifest_sha256,
                "expiresAt": utc(row.expires_at).isoformat(),
            }
            for row in rows
        ],
        "dispatchEnabled": False,
    }


@router.post("/bridge/handoffs/{authorization_id}/claim")
async def claim(
    authorization_id: UUID, bridge: BridgePrincipal, session: DatabaseSession
) -> dict[str, object]:
    row, job = await handoff_access(session, bridge, authorization_id)
    if row.consumed_at is not None:
        raise HTTPException(409, "This handoff was already consumed")
    await session.execute(
        update(PrintAuthorization)
        .where(PrintAuthorization.id == row.id, PrintAuthorization.claimed_at.is_(None))
        .values(claimed_at=utc())
    )
    items, _ = await manifest(session, job)
    await session.commit()
    return {
        "manifestSha256": row.manifest_sha256,
        "dispatchEnabled": False,
        "items": [
            {
                "id": item.id,
                "position": item.position,
                "quantity": item.quantity,
                "sha256": item.artifact_sha256,
                "resultId": str(item.analysis_asset_result_id),
                "downloadUrl": f"/api/v1/bridge/handoffs/{row.id}/artifacts/{item.id}",
            }
            for item in items
        ],
    }


@router.get("/bridge/handoffs/{authorization_id}/artifacts/{item_id}")
async def artifact(
    authorization_id: UUID,
    item_id: UUID,
    bridge: BridgePrincipal,
    session: DatabaseSession,
    storage: Storage,
) -> FileResponse:
    row, job = await handoff_access(session, bridge, authorization_id)
    item = await session.get(PrintJobItem, item_id)
    if (
        row.claimed_at is None
        or row.consumed_at is not None
        or item is None
        or item.print_job_id != job.id
    ):
        raise HTTPException(404, "Artifact not found")
    # The shared downloader verifies private storage bytes against the immutable approved hash.
    response = await artifact_response(job.id, item_id, session, storage)
    try:
        # Storage I/O can be slow: recheck revocation/expiry before exposing the fetched bytes.
        fresh, _ = await handoff_access(session, bridge, authorization_id)
        if fresh.consumed_at is not None:
            raise HTTPException(409, "The handoff was consumed during download")
    except Exception:
        if response.background:
            await response.background()
        raise
    return response


@router.post("/bridge/handoffs/{authorization_id}/received", status_code=204)
async def received(
    authorization_id: UUID, bridge: BridgePrincipal, session: DatabaseSession
) -> None:
    row, _job = await handoff_access(session, bridge, authorization_id)
    if row.claimed_at is None or row.consumed_at is not None:
        raise HTTPException(409, "Claim this handoff once before acknowledging receipt")
    changed = await session.scalar(
        update(PrintAuthorization)
        .where(
            PrintAuthorization.id == row.id,
            PrintAuthorization.consumed_at.is_(None),
            PrintAuthorization.revoked_at.is_(None),
            PrintAuthorization.expires_at > utc(),
        )
        .values(consumed_at=utc(), result_code="downloaded_manual_handoff_only")
        .returning(PrintAuthorization.id)
        .execution_options(synchronize_session="fetch")
    )
    if changed is None:
        raise HTTPException(409, "This handoff was consumed, revoked or expired")
    await session.commit()
