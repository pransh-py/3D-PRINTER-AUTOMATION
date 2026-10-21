"""Buyer orders and MFA-protected owner quotation/production operations."""

from hashlib import file_digest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import case, select
from starlette.background import BackgroundTask

from xxx_api.config import Settings
from xxx_api.dependencies import (
    CurrentPrincipal,
    DatabaseSession,
    OwnerPrincipal,
    RecentMfaOwnerPrincipal,
    SessionCsrf,
    get_object_storage,
    get_rate_limiter,
    get_runtime_settings,
    require_trusted_origin,
)
from xxx_api.domain.auth import AuditEventType
from xxx_api.domain.quotes import ModelAssetStatus
from xxx_api.domain.roles import Role
from xxx_api.models.analysis import AnalysisAssetResult, AnalysisRun
from xxx_api.models.commerce import (
    Fulfillment,
    Order,
    PrintAuthorization,
    PrintJob,
    PrintJobEvent,
    PrintJobItem,
    Quote,
)
from xxx_api.models.quotes import ModelAsset, QuoteRequest
from xxx_api.rate_limit import (
    RateLimiter,
    RateLimitExceededError,
    RateLimitRule,
    RateLimitUnavailableError,
)
from xxx_api.schemas.commerce import (
    AcceptQuoteInput,
    FulfillmentInput,
    FulfillmentOutput,
    IssueQuoteInput,
    JobActionInput,
    JobOutput,
    OrderOutput,
    QuoteOutput,
    ReadinessInput,
    RejectInput,
    VersionInput,
)
from xxx_api.services.audit import append_audit_event
from xxx_api.services.commerce import (
    accept_quote,
    complete_readiness,
    get_order,
    issue_quote,
    manifest,
    reject_request,
    retry_slicing,
    transition_job,
    update_fulfillment,
    utc,
)
from xxx_api.storage import ObjectStorage, ObjectStorageError


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


async def enforce_workflow_limit(
    request: Request,
    principal: CurrentPrincipal,
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> None:
    try:
        await limiter.enforce(
            "workflow-read" if request.method == "GET" else "workflow-write",
            (
                RateLimitRule(
                    str(principal.user.id),
                    limit=120 if request.method == "GET" else 30,
                    window_seconds=60,
                ),
            ),
        )
    except RateLimitExceededError as error:
        raise HTTPException(
            429,
            "Too many workflow requests",
            headers={"Retry-After": str(error.retry_after_seconds), "Cache-Control": "no-store"},
        ) from error
    except RateLimitUnavailableError as error:
        raise HTTPException(
            503,
            "Workflow protection is temporarily unavailable",
            headers={"Cache-Control": "no-store"},
        ) from error


router = APIRouter(
    tags=["commerce"], dependencies=[Depends(no_store), Depends(enforce_workflow_limit)]
)
TrustedOrigin = Annotated[None, Depends(require_trusted_origin)]
Storage = Annotated[ObjectStorage, Depends(get_object_storage)]


@router.get("/owner/quote-requests/{request_id}/models/{asset_id}")
async def review_model(
    request_id: UUID,
    asset_id: UUID,
    request: Request,
    owner: OwnerPrincipal,
    session: DatabaseSession,
    storage: Storage,
    settings: Annotated[Settings, Depends(get_runtime_settings)],
) -> FileResponse:
    """Review a validated source privately; never expose quarantine or object-store paths."""
    asset = await session.scalar(
        select(ModelAsset).where(
            ModelAsset.id == asset_id,
            ModelAsset.quote_request_id == request_id,
            ModelAsset.status == ModelAssetStatus.VALIDATED,
        )
    )
    if asset is None or not asset.verified_sha256:
        raise HTTPException(404, "Validated model not found")
    scratch = TemporaryDirectory(prefix="xxx-model-review-")
    target = Path(scratch.name) / "model"
    try:
        await storage.download_to_path(
            asset.storage_key, target, max_bytes=settings.max_model_file_bytes
        )
        with target.open("rb") as source:
            if file_digest(source, "sha256").hexdigest() != asset.verified_sha256:
                raise HTTPException(409, "Model integrity check failed")
        append_audit_event(
            session,
            AuditEventType.MODEL_SOURCE_ACCESSED,
            actor_user_id=owner.user.id,
            occurred_at=utc(),
            request_id=getattr(request.state, "request_id", None),
            details={"quote_request_id": str(request_id), "asset_id": str(asset_id)},
        )
        await session.commit()
    except ObjectStorageError as error:
        scratch.cleanup()
        raise HTTPException(503, "Private model is temporarily unavailable") from error
    except Exception:
        scratch.cleanup()
        raise
    return FileResponse(
        target,
        media_type="application/octet-stream",
        filename=f"model-{asset.id}.{asset.declared_format.value}",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        background=BackgroundTask(scratch.cleanup),
    )


@router.post("/owner/quote-requests/{request_id}/analysis-retry")
async def retry(
    request_id: UUID,
    payload: VersionInput,
    _origin: TrustedOrigin,
    _csrf: SessionCsrf,
    owner: RecentMfaOwnerPrincipal,
    session: DatabaseSession,
    settings: Annotated[Settings, Depends(get_runtime_settings)],
) -> dict[str, object]:
    if settings.analysis_slicer_command is None:
        raise HTTPException(409, "Configure reviewed AD5X slicing profiles and executable first")
    run = await retry_slicing(session, owner.user, request_id, payload.expected_version)
    return {"id": run.id, "status": run.status}


@router.get("/quotations")
async def quotations(
    principal: CurrentPrincipal,
    session: DatabaseSession,
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, object]:
    statement = select(Quote, QuoteRequest.fulfillment_mode, QuoteRequest.quantity).join(
        QuoteRequest
    )
    if principal.user.role is not Role.OWNER:
        statement = statement.where(QuoteRequest.buyer_id == principal.user.id)
    rows = await session.execute(statement.order_by(Quote.issued_at.desc()).limit(limit))
    return {
        "items": [
            {
                **QuoteOutput.model_validate(quote).model_dump(mode="json", by_alias=True),
                "fulfillmentMode": mode,
                "quantity": quantity,
            }
            for quote, mode, quantity in rows
        ]
    }


@router.get("/quote-requests/previews/{result_id}")
async def preview(
    result_id: UUID, principal: CurrentPrincipal, session: DatabaseSession, storage: Storage
) -> FileResponse:
    statement = (
        select(AnalysisAssetResult)
        .join(AnalysisRun)
        .join(QuoteRequest)
        .where(AnalysisAssetResult.id == result_id)
    )
    if principal.user.role is not Role.OWNER:
        statement = statement.where(QuoteRequest.buyer_id == principal.user.id)
    result = await session.scalar(statement)
    if result is None or not result.preview_storage_key or not result.preview_sha256:
        raise HTTPException(404, "Preview not found")
    scratch = TemporaryDirectory(prefix="xxx-preview-")
    target = Path(scratch.name) / "preview.png"
    try:
        await storage.download_to_path(
            result.preview_storage_key, target, max_bytes=2 * 1024 * 1024
        )
        with target.open("rb") as source:
            if file_digest(source, "sha256").hexdigest() != result.preview_sha256:
                raise HTTPException(409, "Preview integrity check failed")
    except Exception:
        scratch.cleanup()
        raise
    return FileResponse(
        target,
        media_type="image/png",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        background=BackgroundTask(scratch.cleanup),
    )


@router.post(
    "/owner/quote-requests/{request_id}/quotations", response_model=QuoteOutput, status_code=201
)
async def issue(
    request_id: UUID,
    payload: IssueQuoteInput,
    _origin: TrustedOrigin,
    _csrf: SessionCsrf,
    owner: RecentMfaOwnerPrincipal,
    session: DatabaseSession,
) -> QuoteOutput:
    quote = await issue_quote(
        session, owner=owner.user, request_id=request_id, **payload.model_dump()
    )
    return QuoteOutput.model_validate(quote)


@router.post("/owner/quote-requests/{request_id}/reject")
async def reject(
    request_id: UUID,
    payload: RejectInput,
    _origin: TrustedOrigin,
    _csrf: SessionCsrf,
    owner: RecentMfaOwnerPrincipal,
    session: DatabaseSession,
) -> dict[str, object]:
    record = await reject_request(
        session, owner=owner.user, request_id=request_id, **payload.model_dump()
    )
    return {"id": record.id, "status": record.status, "version": record.version}


@router.post("/quotations/{quote_id}/accept", response_model=OrderOutput)
async def accept(
    quote_id: UUID,
    payload: AcceptQuoteInput,
    _origin: TrustedOrigin,
    _csrf: SessionCsrf,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> OrderOutput:
    order = await accept_quote(
        session,
        buyer=principal.user,
        quote_id=quote_id,
        address=payload.address.model_dump(mode="json", by_alias=True) if payload.address else None,
    )
    return OrderOutput.model_validate(order)


@router.get("/orders")
async def orders(
    principal: CurrentPrincipal,
    session: DatabaseSession,
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, object]:
    statement = select(Order)
    if principal.user.role is not Role.OWNER:
        statement = statement.where(Order.buyer_id == principal.user.id)
    rows = await session.scalars(statement.order_by(Order.accepted_at.desc()).limit(limit))
    return {
        "items": [
            OrderOutput.model_validate(row).model_dump(mode="json", by_alias=True) for row in rows
        ]
    }


@router.get("/orders/{order_id}")
async def order_detail(
    order_id: UUID,
    principal: CurrentPrincipal,
    session: DatabaseSession,
    settings: Annotated[Settings, Depends(get_runtime_settings)],
) -> dict[str, object]:
    order = await get_order(session, user=principal.user, order_id=order_id)
    jobs = list(
        await session.scalars(
            select(PrintJob).where(PrintJob.order_id == order.id).order_by(PrintJob.sequence)
        )
    )
    fulfillment = await session.scalar(select(Fulfillment).where(Fulfillment.order_id == order.id))
    events = list(
        await session.scalars(
            select(PrintJobEvent)
            .join(PrintJob)
            .where(PrintJob.order_id == order.id)
            .order_by(PrintJobEvent.received_at)
            .limit(100)
        )
    )
    return {
        **OrderOutput.model_validate(order).model_dump(mode="json", by_alias=True),
        "lines": order.commercial_snapshot.get("lines", []),
        "jobs": [{"id": job.id, "status": job.status, "sequence": job.sequence} for job in jobs],
        "fulfillment": FulfillmentOutput.model_validate(fulfillment).model_dump(
            mode="json", by_alias=True
        )
        if fulfillment
        else None,
        "timeline": [
            {
                "event": event.event_type,
                "at": utc(event.received_at).isoformat(),
                "progressBps": event.progress_bps,
            }
            for event in events
        ],
        "payment": {
            "checkoutEnabled": settings.razorpay_enabled,
            "testMode": settings.razorpay_enabled and settings.razorpay_mode == "test",
            "message": (
                "Test payment only. No real money is collected."
                if settings.razorpay_enabled and settings.razorpay_mode == "test"
                else "Payment is confirmed by the server, not by closing Checkout."
                if settings.razorpay_enabled
                else "Online payment is not configured yet. Your accepted quote is saved."
            ),
        },
    }


@router.get("/owner/production")
async def production(
    _owner: OwnerPrincipal, session: DatabaseSession, limit: int = Query(default=50, ge=1, le=100)
) -> dict[str, object]:
    jobs = await session.scalars(
        select(PrintJob)
        .where(PrintJob.status.not_in(["completed", "cancelled"]))
        .order_by(
            case((PrintJob.status.in_(["failed", "on_hold"]), 1), else_=0),
            PrintJob.queue_rank,
            PrintJob.id,
        )
        .limit(limit)
    )
    return {
        "items": [
            JobOutput.model_validate(job).model_dump(mode="json", by_alias=True) for job in jobs
        ]
    }


@router.post("/owner/production/{job_id}/actions", response_model=JobOutput)
async def job_action(
    job_id: UUID,
    payload: JobActionInput,
    _origin: TrustedOrigin,
    _csrf: SessionCsrf,
    owner: RecentMfaOwnerPrincipal,
    session: DatabaseSession,
) -> JobOutput:
    if payload.action == "manual_started":
        active = await session.scalar(
            select(PrintAuthorization.id).where(
                PrintAuthorization.print_job_id == job_id,
                PrintAuthorization.revoked_at.is_(None),
                PrintAuthorization.result_code.in_(["station_authorized", "station_claimed"]),
            )
        )
        if active:
            raise HTTPException(409, "Resolve the automatic station attempt before a manual start.")
    job = await transition_job(session, owner=owner.user, job_id=job_id, **payload.model_dump())
    return JobOutput.model_validate(job)


@router.post("/owner/production/{job_id}/readiness", response_model=JobOutput)
async def readiness(
    job_id: UUID,
    payload: ReadinessInput,
    _origin: TrustedOrigin,
    _csrf: SessionCsrf,
    owner: RecentMfaOwnerPrincipal,
    session: DatabaseSession,
) -> JobOutput:
    job = await complete_readiness(
        session,
        owner=owner.user,
        job_id=job_id,
        expected_version=payload.expected_version,
        checklist=payload.model_dump(by_alias=True, exclude={"expected_version"}),
    )
    return JobOutput.model_validate(job)


@router.get("/owner/production/{job_id}/artifacts")
async def artifacts(
    job_id: UUID, _owner: OwnerPrincipal, session: DatabaseSession
) -> dict[str, object]:
    job = await session.get(PrintJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    items, digest = await manifest(session, job)
    return {
        "manifestSha256": digest,
        "items": [
            {
                "id": item.id,
                "position": item.position,
                "quantity": item.quantity,
                "sha256": item.artifact_sha256,
                "downloadUrl": f"/api/v1/owner/production/{job_id}/artifacts/{item.id}",
            }
            for item in items
        ],
    }


@router.get("/owner/production/{job_id}/artifacts/{item_id}")
async def download_artifact(
    job_id: UUID,
    item_id: UUID,
    _owner: RecentMfaOwnerPrincipal,
    session: DatabaseSession,
    storage: Storage,
) -> FileResponse:
    return await artifact_response(job_id, item_id, session, storage)


async def artifact_response(
    job_id: UUID, item_id: UUID, session: DatabaseSession, storage: ObjectStorage
) -> FileResponse:
    job = await session.get(PrintJob, job_id)
    item = await session.get(PrintJobItem, item_id)
    if job is None or item is None or item.print_job_id != job_id:
        raise HTTPException(404, "Artifact not found")
    await manifest(session, job)
    scratch = TemporaryDirectory(prefix="xxx-artifact-")
    target = Path(scratch.name) / "approved.gcode"
    try:
        await storage.download_to_path(
            item.artifact_storage_key, target, max_bytes=200 * 1024 * 1024
        )
        with target.open("rb") as source:
            if file_digest(source, "sha256").hexdigest() != item.artifact_sha256:
                raise HTTPException(409, "Stored artifact does not match the approved hash")
    except Exception:
        scratch.cleanup()
        raise
    return FileResponse(
        target,
        media_type="application/octet-stream",
        filename=f"job-{job.id}-{item.position}.gcode",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        background=BackgroundTask(scratch.cleanup),
    )


@router.post("/owner/orders/{order_id}/fulfillment", response_model=FulfillmentOutput)
async def fulfill(
    order_id: UUID,
    payload: FulfillmentInput,
    _origin: TrustedOrigin,
    _csrf: SessionCsrf,
    owner: RecentMfaOwnerPrincipal,
    session: DatabaseSession,
) -> FulfillmentOutput:
    record = await update_fulfillment(
        session, owner=owner.user, order_id=order_id, **payload.model_dump()
    )
    return FulfillmentOutput.model_validate(record)
