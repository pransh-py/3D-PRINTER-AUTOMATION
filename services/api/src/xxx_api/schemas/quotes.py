"""Public quote-request and private-upload schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from xxx_api.domain.quotes import ModelAssetStatus, ModelFormat, QuoteRequestStatus


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


class QuoteRequestListResponse(QuoteSchema):
    """Bounded list response for buyer and owner views."""

    items: list[QuoteRequestResponse]
    total: int
    limit: int
    offset: int
