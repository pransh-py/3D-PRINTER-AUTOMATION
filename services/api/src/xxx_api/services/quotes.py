"""Transactional quote-request and private model-upload intake."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath
from unicodedata import category, normalize
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from xxx_api.config import Settings
from xxx_api.domain.auth import AuditEventType
from xxx_api.domain.quotes import ModelAssetStatus, ModelFormat, QuoteRequestStatus
from xxx_api.domain.roles import Role
from xxx_api.models.identity import User
from xxx_api.models.quotes import ModelAsset, QuoteRequest
from xxx_api.services.audit import append_audit_event
from xxx_api.storage import ObjectNotFoundError, ObjectStorage, PresignedPost

UPLOAD_CONTENT_TYPE = "application/octet-stream"
FORMAT_BY_EXTENSION = {
    ".stl": ModelFormat.STL,
    ".3mf": ModelFormat.THREE_MF,
    ".obj": ModelFormat.OBJ,
    ".step": ModelFormat.STEP,
    ".stp": ModelFormat.STEP,
}


class QuoteRequestError(Exception):
    """Base quote-intake failure translated by HTTP adapters."""


class QuoteRequestNotFoundError(QuoteRequestError):
    """The request is absent or hidden by resource ownership."""


class QuoteRequestConflictError(QuoteRequestError):
    """The requested operation conflicts with persisted workflow state."""


class InvalidModelUploadError(QuoteRequestError):
    """Declared or observed upload evidence is invalid."""


class ModelUploadNotFoundError(QuoteRequestError):
    """The expected private object is not yet available."""


@dataclass(frozen=True, slots=True)
class ModelUploadIssue:
    """Persisted pending asset and its short-lived signed POST."""

    asset: ModelAsset
    upload: PresignedPost


def _utc_now(now: datetime | None) -> datetime:
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _safe_filename(value: str) -> tuple[str, ModelFormat]:
    leaf = value.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    visible_characters = "".join(
        character for character in leaf if category(character) != "Cc"
    )
    clean = normalize("NFC", visible_characters)
    clean = clean.strip()
    if not clean or clean in {".", ".."} or len(clean) > 255:
        raise InvalidModelUploadError("filename is invalid")
    model_format = FORMAT_BY_EXTENSION.get(PurePath(clean).suffix.lower())
    if model_format is None:
        raise InvalidModelUploadError("model format is not supported")
    return clean, model_format


def _can_read(user: User, request: QuoteRequest) -> bool:
    return user.role is Role.OWNER or request.buyer_id == user.id


async def _visible_request(
    session: AsyncSession,
    user: User,
    request_id: UUID,
    *,
    lock: bool = False,
) -> QuoteRequest:
    statement = (
        select(QuoteRequest)
        .where(QuoteRequest.id == request_id)
        .options(selectinload(QuoteRequest.assets))
    )
    if lock:
        statement = statement.with_for_update()
    request = await session.scalar(statement)
    if request is None or not _can_read(user, request):
        await session.rollback()
        raise QuoteRequestNotFoundError
    return request


async def create_quote_request(
    session: AsyncSession,
    *,
    buyer: User,
    client_token: UUID,
    now: datetime | None = None,
    audit_request_id: str | None = None,
) -> QuoteRequest:
    """Create or return one buyer-idempotent draft quote request."""
    if buyer.role is not Role.BUYER:
        raise QuoteRequestConflictError("only buyers create quote requests")
    existing = await session.scalar(
        select(QuoteRequest)
        .where(
            QuoteRequest.buyer_id == buyer.id,
            QuoteRequest.client_token == client_token,
        )
        .options(selectinload(QuoteRequest.assets))
    )
    if existing is not None:
        return existing
    created_at = _utc_now(now)
    request = QuoteRequest(
        id=uuid4(),
        buyer_id=buyer.id,
        client_token=client_token,
        status=QuoteRequestStatus.DRAFT,
        version=1,
        created_at=created_at,
        updated_at=created_at,
        assets=[],
    )
    session.add(request)
    try:
        await session.flush()
        append_audit_event(
            session,
            AuditEventType.QUOTE_REQUEST_CREATED,
            occurred_at=created_at,
            actor_user_id=buyer.id,
            target_user_id=buyer.id,
            request_id=audit_request_id,
            details={"quote_request_id": str(request.id)},
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        repeated = await session.scalar(
            select(QuoteRequest)
            .where(
                QuoteRequest.buyer_id == buyer.id,
                QuoteRequest.client_token == client_token,
            )
            .options(selectinload(QuoteRequest.assets))
        )
        if repeated is None:
            raise
        return repeated
    return request


async def list_quote_requests(
    session: AsyncSession,
    *,
    user: User,
    limit: int,
    offset: int,
) -> tuple[list[QuoteRequest], int]:
    """List only buyer-owned requests, or every request for the owner."""
    filters = [] if user.role is Role.OWNER else [QuoteRequest.buyer_id == user.id]
    total = await session.scalar(select(func.count()).select_from(QuoteRequest).where(*filters))
    requests = list(
        await session.scalars(
            select(QuoteRequest)
            .where(*filters)
            .options(selectinload(QuoteRequest.assets))
            .order_by(QuoteRequest.created_at.desc(), QuoteRequest.id)
            .limit(limit)
            .offset(offset)
        )
    )
    return requests, int(total or 0)


async def get_quote_request(
    session: AsyncSession,
    *,
    user: User,
    request_id: UUID,
) -> QuoteRequest:
    """Read one request through owner-or-owner-resource authorization."""
    return await _visible_request(session, user, request_id)


async def create_model_upload(
    session: AsyncSession,
    settings: Settings,
    storage: ObjectStorage,
    *,
    buyer: User,
    request_id: UUID,
    client_token: UUID,
    filename: str,
    size_bytes: int,
    sha256: str,
    now: datetime | None = None,
    audit_request_id: str | None = None,
) -> ModelUploadIssue:
    """Persist a constrained upload intent and issue its short-lived signed POST."""
    if buyer.role is not Role.BUYER:
        raise QuoteRequestNotFoundError
    clean_filename, model_format = _safe_filename(filename)
    if size_bytes < 1 or size_bytes > settings.max_model_file_bytes:
        raise InvalidModelUploadError("model file size is outside the allowed range")
    if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
        raise InvalidModelUploadError("SHA-256 claim is invalid")
    request = await _visible_request(session, buyer, request_id, lock=True)
    if request.status is not QuoteRequestStatus.DRAFT:
        await session.rollback()
        raise QuoteRequestConflictError("quote request is no longer editable")
    existing = await session.scalar(
        select(ModelAsset).where(
            ModelAsset.quote_request_id == request.id,
            ModelAsset.client_token == client_token,
        )
    )
    if existing is not None:
        if (
            existing.original_filename != clean_filename
            or existing.expected_size_bytes != size_bytes
            or existing.claimed_sha256 != sha256
        ):
            await session.rollback()
            raise QuoteRequestConflictError("upload idempotency token was reused")
        if existing.status is not ModelAssetStatus.PENDING_UPLOAD:
            await session.rollback()
            raise QuoteRequestConflictError("upload intent is no longer pending")
        upload = await storage.create_upload(
            key=existing.storage_key,
            size_bytes=existing.expected_size_bytes,
            content_type=existing.declared_content_type,
            metadata={"asset-id": str(existing.id), "sha256": existing.claimed_sha256},
        )
        existing.upload_expires_at = upload.expires_at
        await session.commit()
        return ModelUploadIssue(existing, upload)

    active_assets = await session.scalar(
        select(func.count())
        .select_from(ModelAsset)
        .where(
            ModelAsset.quote_request_id == request.id,
            ModelAsset.status != ModelAssetStatus.REJECTED,
        )
    )
    if int(active_assets or 0) >= settings.max_models_per_quote:
        await session.rollback()
        raise QuoteRequestConflictError("quote request already has the maximum model files")
    asset_id = uuid4()
    storage_key = f"models/original/{buyer.id}/{request.id}/{asset_id}/source"
    upload = await storage.create_upload(
        key=storage_key,
        size_bytes=size_bytes,
        content_type=UPLOAD_CONTENT_TYPE,
        metadata={"asset-id": str(asset_id), "sha256": sha256},
    )
    created_at = _utc_now(now)
    asset = ModelAsset(
        id=asset_id,
        quote_request_id=request.id,
        client_token=client_token,
        original_filename=clean_filename,
        declared_format=model_format,
        declared_content_type=UPLOAD_CONTENT_TYPE,
        expected_size_bytes=size_bytes,
        claimed_sha256=sha256,
        storage_key=storage_key,
        status=ModelAssetStatus.PENDING_UPLOAD,
        upload_expires_at=upload.expires_at,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(asset)
    append_audit_event(
        session,
        AuditEventType.MODEL_UPLOAD_ISSUED,
        occurred_at=created_at,
        actor_user_id=buyer.id,
        target_user_id=buyer.id,
        request_id=audit_request_id,
        details={
            "quote_request_id": str(request.id),
            "model_asset_id": str(asset.id),
            "format": model_format.value,
            "size_bytes": size_bytes,
        },
    )
    try:
        await session.commit()
        return ModelUploadIssue(asset, upload)
    except IntegrityError as error:
        await session.rollback()
        repeated = await session.scalar(
            select(ModelAsset).where(
                ModelAsset.quote_request_id == request.id,
                ModelAsset.client_token == client_token,
            )
        )
        if repeated is None:
            raise
        if (
            repeated.original_filename != clean_filename
            or repeated.expected_size_bytes != size_bytes
            or repeated.claimed_sha256 != sha256
            or repeated.status is not ModelAssetStatus.PENDING_UPLOAD
        ):
            raise QuoteRequestConflictError("upload idempotency token was reused") from error
        repeated_upload = await storage.create_upload(
            key=repeated.storage_key,
            size_bytes=repeated.expected_size_bytes,
            content_type=repeated.declared_content_type,
            metadata={"asset-id": str(repeated.id), "sha256": repeated.claimed_sha256},
        )
        repeated.upload_expires_at = repeated_upload.expires_at
        await session.commit()
        return ModelUploadIssue(repeated, repeated_upload)


async def complete_model_upload(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    buyer: User,
    request_id: UUID,
    asset_id: UUID,
    now: datetime | None = None,
    audit_request_id: str | None = None,
) -> ModelAsset:
    """Admit a storage object to quarantine only after exact metadata checks."""
    if buyer.role is not Role.BUYER:
        raise QuoteRequestNotFoundError
    request = await _visible_request(session, buyer, request_id, lock=True)
    asset = await session.scalar(
        select(ModelAsset)
        .where(ModelAsset.id == asset_id, ModelAsset.quote_request_id == request.id)
        .with_for_update()
    )
    if asset is None:
        await session.rollback()
        raise QuoteRequestNotFoundError
    if asset.status is ModelAssetStatus.QUARANTINED:
        return asset
    if asset.status is not ModelAssetStatus.PENDING_UPLOAD:
        await session.rollback()
        raise QuoteRequestConflictError("upload cannot be completed from its current state")
    try:
        observed = await storage.head(asset.storage_key)
    except ObjectNotFoundError as error:
        await session.rollback()
        raise ModelUploadNotFoundError from error
    expected_metadata = {"asset-id": str(asset.id), "sha256": asset.claimed_sha256}
    matches = (
        observed.size_bytes == asset.expected_size_bytes
        and observed.content_type == asset.declared_content_type
        and all(observed.metadata.get(key) == value for key, value in expected_metadata.items())
    )
    completed_at = _utc_now(now)
    if not matches:
        await storage.delete(asset.storage_key)
        asset.status = ModelAssetStatus.REJECTED
        asset.rejection_code = "upload_metadata_mismatch"
        append_audit_event(
            session,
            AuditEventType.MODEL_UPLOAD_REJECTED,
            occurred_at=completed_at,
            actor_user_id=buyer.id,
            target_user_id=buyer.id,
            request_id=audit_request_id,
            details={"quote_request_id": str(request.id), "model_asset_id": str(asset.id)},
        )
        await session.commit()
        raise InvalidModelUploadError("uploaded object did not match its signed declaration")
    asset.actual_size_bytes = observed.size_bytes
    asset.storage_etag = observed.etag
    asset.uploaded_at = completed_at
    asset.status = ModelAssetStatus.QUARANTINED
    append_audit_event(
        session,
        AuditEventType.MODEL_UPLOAD_COMPLETED,
        occurred_at=completed_at,
        actor_user_id=buyer.id,
        target_user_id=buyer.id,
        request_id=audit_request_id,
        details={"quote_request_id": str(request.id), "model_asset_id": str(asset.id)},
    )
    await session.commit()
    return asset


async def submit_quote_request(
    session: AsyncSession,
    *,
    buyer: User,
    request_id: UUID,
    now: datetime | None = None,
    audit_request_id: str | None = None,
) -> QuoteRequest:
    """Freeze a complete draft and hand it to the future analysis pipeline."""
    if buyer.role is not Role.BUYER:
        raise QuoteRequestNotFoundError
    request = await _visible_request(session, buyer, request_id, lock=True)
    if request.status is QuoteRequestStatus.ANALYZING:
        return request
    if request.status is not QuoteRequestStatus.DRAFT:
        await session.rollback()
        raise QuoteRequestConflictError("quote request cannot be submitted")
    active = [asset for asset in request.assets if asset.status is not ModelAssetStatus.REJECTED]
    if not active or any(asset.status is not ModelAssetStatus.QUARANTINED for asset in active):
        await session.rollback()
        raise QuoteRequestConflictError("every active model upload must be complete")
    submitted_at = _utc_now(now)
    request.status = QuoteRequestStatus.ANALYZING
    request.submitted_at = submitted_at
    request.version += 1
    append_audit_event(
        session,
        AuditEventType.QUOTE_REQUEST_SUBMITTED,
        occurred_at=submitted_at,
        actor_user_id=buyer.id,
        target_user_id=buyer.id,
        request_id=audit_request_id,
        details={"quote_request_id": str(request.id), "model_count": len(active)},
    )
    await session.commit()
    await session.refresh(request, attribute_names=["updated_at"])
    return request
