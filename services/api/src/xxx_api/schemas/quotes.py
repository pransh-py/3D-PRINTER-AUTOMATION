"""Public quote-request and private-upload schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from xxx_api.domain.quotes import (
    AnalysisAssetStatus,
    AnalysisRunStatus,
    ModelAssetStatus,
    ModelFormat,
    QuoteRequestStatus,
)


class QuoteSchema(BaseModel):
    """Strict camelCase-compatible schema base."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CreateQuoteRequest(QuoteSchema):
    """Idempotent request creation input."""

    client_token: UUID = Field(alias="clientToken")


class CreateModelUploadRequest(QuoteSchema):
    """Declared source evidence used to constrain one presigned upload."""

    client_token: UUID = Field(alias="clientToken")
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(alias="sizeBytes", ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PresignedUploadResponse(QuoteSchema):
    """Short-lived POST target and signed form fields."""

    url: str
    fields: dict[str, str]
    expires_at: datetime = Field(alias="expiresAt")


class ModelAssetResponse(QuoteSchema):
    """Private model metadata without its storage key."""

    id: UUID
    filename: str
    format: ModelFormat
    status: ModelAssetStatus
    expected_size_bytes: int = Field(alias="expectedSizeBytes")
    actual_size_bytes: int | None = Field(alias="actualSizeBytes")
    claimed_sha256: str = Field(alias="claimedSha256")
    verified_sha256: str | None = Field(alias="verifiedSha256")
    upload_expires_at: datetime = Field(alias="uploadExpiresAt")
    uploaded_at: datetime | None = Field(alias="uploadedAt")
    rejection_code: str | None = Field(alias="rejectionCode")
    created_at: datetime = Field(alias="createdAt")


class ModelUploadIntentResponse(QuoteSchema):
    """Persisted asset plus its one-time browser upload material."""

    asset: ModelAssetResponse
    upload: PresignedUploadResponse


class AnalysisAssetResultResponse(QuoteSchema):
    """Buyer-safe, bounded evidence for one model asset."""

    asset_id: UUID = Field(alias="assetId")
    status: AnalysisAssetStatus
    detected_format: ModelFormat | None = Field(alias="detectedFormat")
    verified_sha256: str | None = Field(alias="verifiedSha256")
    dimensions_um: tuple[int, int, int] | None = Field(alias="dimensionsUm")
    triangle_count: int | None = Field(alias="triangleCount")
    object_count: int | None = Field(alias="objectCount")
    fits_build_volume: bool | None = Field(alias="fitsBuildVolume")
    warning_codes: list[str] = Field(alias="warningCodes")
    filament_mg: int | None = Field(alias="filamentMg")
    duration_seconds: int | None = Field(alias="durationSeconds")
    failure_code: str | None = Field(alias="failureCode")


class AnalysisRunResponse(QuoteSchema):
    """Latest versioned analysis state without private worker diagnostics."""

    id: UUID
    request_version: int = Field(alias="requestVersion")
    status: AnalysisRunStatus
    attempt_count: int = Field(alias="attemptCount")
    validator_version: str = Field(alias="validatorVersion")
    slicer_name: str | None = Field(alias="slicerName")
    slicer_version: str | None = Field(alias="slicerVersion")
    profile_sha256: str | None = Field(alias="profileSha256")
    queued_at: datetime = Field(alias="queuedAt")
    started_at: datetime | None = Field(alias="startedAt")
    completed_at: datetime | None = Field(alias="completedAt")
    failure_code: str | None = Field(alias="failureCode")
    assets: list[AnalysisAssetResultResponse]


class QuoteRequestResponse(QuoteSchema):
    """Buyer-safe quote-request representation."""

    id: UUID
    buyer_id: UUID = Field(alias="buyerId")
    status: QuoteRequestStatus
    version: int
    submitted_at: datetime | None = Field(alias="submittedAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    assets: list[ModelAssetResponse]
    latest_analysis: AnalysisRunResponse | None = Field(alias="latestAnalysis")


class QuoteRequestListResponse(QuoteSchema):
    """Bounded list response for buyer and owner views."""

    items: list[QuoteRequestResponse]
    total: int
    limit: int
    offset: int
