"""Authenticated quote-request and private model-upload HTTP adapters."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from xxx_api.config import Settings
from xxx_api.dependencies import (
    CurrentPrincipal,
    DatabaseSession,
    SessionCsrf,
    get_object_storage,
    get_rate_limiter,
    get_runtime_settings,
    require_trusted_origin,
)
from xxx_api.models.analysis import AnalysisAssetResult, AnalysisRun
from xxx_api.models.quotes import ModelAsset, QuoteRequest
from xxx_api.rate_limit import (
    RateLimiter,
    RateLimitExceededError,
    RateLimitRule,
    RateLimitUnavailableError,
)
from xxx_api.schemas.quotes import (
    AnalysisAssetResultResponse,
    AnalysisRunResponse,
    CreateModelUploadRequest,
    CreateQuoteRequest,
    ModelAssetResponse,
    ModelUploadIntentResponse,
    PresignedUploadResponse,
    QuoteRequestListResponse,
    QuoteRequestResponse,
)
from xxx_api.services.quotes import (
    InvalidModelUploadError,
    ModelUploadNotFoundError,
    QuoteRequestConflictError,
    QuoteRequestNotFoundError,
    complete_model_upload,
    create_model_upload,
    create_quote_request,
    get_quote_request,
    list_quote_requests,
    submit_quote_request,
)
from xxx_api.storage import ObjectStorage, ObjectStorageError

router = APIRouter(prefix="/quote-requests", tags=["quotes"])
TrustedOrigin = Annotated[None, Depends(require_trusted_origin)]
RuntimeSettings = Annotated[Settings, Depends(get_runtime_settings)]
Limiter = Annotated[RateLimiter, Depends(get_rate_limiter)]
PrivateStorage = Annotated[ObjectStorage, Depends(get_object_storage)]


def _request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else None


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


async def _enforce_upload_limit(
    limiter: RateLimiter,
    request: Request,
    user_id: UUID,
) -> None:
    client = request.client.host if request.client is not None else "unknown"
    try:
        await limiter.enforce(
            "model-upload-issue",
            (
                RateLimitRule(client, limit=30, window_seconds=15 * 60),
                RateLimitRule(str(user_id), limit=20, window_seconds=60 * 60),
            ),
        )
    except RateLimitExceededError as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many upload requests",
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    except RateLimitUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Upload service temporarily unavailable",
        ) from error


async def _enforce_quote_creation_limit(
    limiter: RateLimiter,
    request: Request,
    user_id: UUID,
) -> None:
    client = request.client.host if request.client is not None else "unknown"
    try:
        await limiter.enforce(
            "quote-request-create",
            (
                RateLimitRule(client, limit=30, window_seconds=15 * 60),
                RateLimitRule(str(user_id), limit=30, window_seconds=60 * 60),
            ),
        )
    except RateLimitExceededError as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many quote requests",
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    except RateLimitUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Quote service temporarily unavailable",
        ) from error


def _asset_response(asset: ModelAsset) -> ModelAssetResponse:
    return ModelAssetResponse(
        id=asset.id,
        filename=asset.original_filename,
        format=asset.declared_format,
        status=asset.status,
        expectedSizeBytes=asset.expected_size_bytes,
        actualSizeBytes=asset.actual_size_bytes,
        claimedSha256=asset.claimed_sha256,
        verifiedSha256=asset.verified_sha256,
        uploadExpiresAt=asset.upload_expires_at,
        uploadedAt=asset.uploaded_at,
        rejectionCode=asset.rejection_code,
        createdAt=asset.created_at,
    )


def _analysis_asset_response(result: AnalysisAssetResult) -> AnalysisAssetResultResponse:
    dimensions = None
    if (
        result.dimension_x_um is not None
        and result.dimension_y_um is not None
        and result.dimension_z_um is not None
    ):
        dimensions = (
            result.dimension_x_um,
            result.dimension_y_um,
            result.dimension_z_um,
        )
    return AnalysisAssetResultResponse(
        assetId=result.model_asset_id,
        status=result.status,
        detectedFormat=result.detected_format,
        verifiedSha256=result.verified_sha256,
        dimensionsUm=dimensions,
        triangleCount=result.triangle_count,
        objectCount=result.object_count,
        fitsBuildVolume=result.fits_build_volume,
        warningCodes=result.warning_codes,
        filamentMg=result.filament_mg,
        durationSeconds=result.duration_seconds,
        failureCode=result.failure_code,
    )


def _analysis_response(run: AnalysisRun) -> AnalysisRunResponse:
    return AnalysisRunResponse(
        id=run.id,
        requestVersion=run.request_version,
        status=run.status,
        attemptCount=run.attempt_count,
        validatorVersion=run.validator_version,
        slicerName=run.slicer_name,
        slicerVersion=run.slicer_version,
        profileSha256=run.profile_sha256,
        queuedAt=run.queued_at,
        startedAt=run.started_at,
        completedAt=run.completed_at,
        failureCode=run.failure_code,
        assets=[_analysis_asset_response(result) for result in run.asset_results],
    )


def _quote_response(quote: QuoteRequest) -> QuoteRequestResponse:
    latest_analysis = quote.analysis_runs[-1] if quote.analysis_runs else None
    return QuoteRequestResponse(
        id=quote.id,
        buyerId=quote.buyer_id,
        status=quote.status,
        version=quote.version,
        submittedAt=quote.submitted_at,
        createdAt=quote.created_at,
        updatedAt=quote.updated_at,
        assets=[_asset_response(asset) for asset in quote.assets],
        latestAnalysis=(
            _analysis_response(latest_analysis) if latest_analysis is not None else None
        ),
    )


@router.post("", response_model=QuoteRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_request(
    payload: CreateQuoteRequest,
    request: Request,
    response: Response,
    _origin: TrustedOrigin,
    _csrf: SessionCsrf,
    principal: CurrentPrincipal,
    session: DatabaseSession,
    limiter: Limiter,
) -> QuoteRequestResponse:
    """Create one buyer-idempotent draft quote request."""
    _private(response)
    await _enforce_quote_creation_limit(limiter, request, principal.user.id)
    try:
        quote = await create_quote_request(
            session,
            buyer=principal.user,
            client_token=payload.client_token,
            audit_request_id=_request_id(request),
        )
    except QuoteRequestConflictError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    return _quote_response(quote)


@router.get("", response_model=QuoteRequestListResponse)
async def list_requests(
    response: Response,
    principal: CurrentPrincipal,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> QuoteRequestListResponse:
    """List buyer-owned requests or all requests for the owner."""
    _private(response)
    requests, total = await list_quote_requests(
        session,
        user=principal.user,
        limit=limit,
        offset=offset,
    )
    return QuoteRequestListResponse(
        items=[_quote_response(quote) for quote in requests],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{request_id}", response_model=QuoteRequestResponse)
async def get_request(
    request_id: UUID,
    response: Response,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> QuoteRequestResponse:
    """Read one owner-visible or buyer-owned request."""
    _private(response)
    try:
        quote = await get_quote_request(session, user=principal.user, request_id=request_id)
    except QuoteRequestNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quote not found",
        ) from error
    return _quote_response(quote)


@router.post(
    "/{request_id}/uploads",
    response_model=ModelUploadIntentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def issue_upload(
    request_id: UUID,
    payload: CreateModelUploadRequest,
    request: Request,
    response: Response,
    _origin: TrustedOrigin,
    _csrf: SessionCsrf,
    principal: CurrentPrincipal,
    session: DatabaseSession,
    settings: RuntimeSettings,
    limiter: Limiter,
    storage: PrivateStorage,
) -> ModelUploadIntentResponse:
    """Issue one exact, short-lived private-storage POST policy."""
    _private(response)
    await _enforce_upload_limit(limiter, request, principal.user.id)
    try:
        issue = await create_model_upload(
            session,
            settings,
            storage,
            buyer=principal.user,
            request_id=request_id,
            client_token=payload.client_token,
            filename=payload.filename,
            size_bytes=payload.size_bytes,
            sha256=payload.sha256,
            audit_request_id=_request_id(request),
        )
    except QuoteRequestNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quote not found",
        ) from error
    except QuoteRequestConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except InvalidModelUploadError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except ObjectStorageError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Upload service temporarily unavailable",
        ) from error
    return ModelUploadIntentResponse(
        asset=_asset_response(issue.asset),
        upload=PresignedUploadResponse(
            url=issue.upload.url,
            fields=issue.upload.fields,
            expiresAt=issue.upload.expires_at,
        ),
    )


@router.post("/{request_id}/uploads/{asset_id}/complete", response_model=ModelAssetResponse)
async def complete_upload(
    request_id: UUID,
    asset_id: UUID,
    request: Request,
    response: Response,
    _origin: TrustedOrigin,
    _csrf: SessionCsrf,
    principal: CurrentPrincipal,
    session: DatabaseSession,
    storage: PrivateStorage,
) -> ModelAssetResponse:
    """Verify storage evidence before moving one object into quarantine."""
    _private(response)
    try:
        asset = await complete_model_upload(
            session,
            storage,
            buyer=principal.user,
            request_id=request_id,
            asset_id=asset_id,
            audit_request_id=_request_id(request),
        )
    except QuoteRequestNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quote not found",
        ) from error
    except ModelUploadNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Uploaded object is not available yet",
        ) from error
    except QuoteRequestConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except InvalidModelUploadError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except ObjectStorageError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Upload service temporarily unavailable",
        ) from error
    return _asset_response(asset)


@router.post("/{request_id}/submit", response_model=QuoteRequestResponse)
async def submit_request(
    request_id: UUID,
    request: Request,
    response: Response,
    _origin: TrustedOrigin,
    _csrf: SessionCsrf,
    principal: CurrentPrincipal,
    session: DatabaseSession,
) -> QuoteRequestResponse:
    """Freeze a complete draft for the analysis queue."""
    _private(response)
    try:
        quote = await submit_quote_request(
            session,
            buyer=principal.user,
            request_id=request_id,
            audit_request_id=_request_id(request),
        )
    except QuoteRequestNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quote not found",
        ) from error
    except QuoteRequestConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return _quote_response(quote)
