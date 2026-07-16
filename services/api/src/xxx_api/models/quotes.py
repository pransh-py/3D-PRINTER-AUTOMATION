"""Quote-request and private model-asset persistence."""

from __future__ import annotations

from datetime import datetime
from enum import Enum as PythonEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from xxx_api.domain.quotes import ModelAssetStatus, ModelFormat, QuoteRequestStatus
from xxx_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def enum_values(enum_class: type[PythonEnum]) -> list[str]:
    """Persist stable enum values rather than Python member names."""
    return [str(member.value) for member in enum_class]


class QuoteRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One buyer-owned request whose workflow is controlled by the server."""

    __tablename__ = "quote_requests"
    __table_args__ = (
        UniqueConstraint("buyer_id", "client_token", name="uq_quote_requests_buyer_client"),
        CheckConstraint("version >= 1", name="ck_quote_requests_version_positive"),
        Index("ix_quote_requests_buyer_created", "buyer_id", "created_at"),
        Index("ix_quote_requests_status_created", "status", "created_at"),
    )

    buyer_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    client_token: Mapped[UUID] = mapped_column(nullable=False)
    status: Mapped[QuoteRequestStatus] = mapped_column(
        Enum(
            QuoteRequestStatus,
            native_enum=False,
            values_callable=enum_values,
            length=32,
            validate_strings=True,
            create_constraint=True,
            name="ck_quote_requests_status",
        ),
        default=QuoteRequestStatus.DRAFT,
        server_default=QuoteRequestStatus.DRAFT.value,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    assets: Mapped[list[ModelAsset]] = relationship(
        back_populates="quote_request",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ModelAsset.created_at",
    )


class ModelAsset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One private source object and its progressively established evidence."""

    __tablename__ = "model_assets"
    __table_args__ = (
        UniqueConstraint(
            "quote_request_id",
            "client_token",
            name="uq_model_assets_request_client",
        ),
        Index("ix_model_assets_request_status", "quote_request_id", "status"),
        CheckConstraint("expected_size_bytes > 0", name="ck_model_assets_expected_size"),
        CheckConstraint(
            "actual_size_bytes IS NULL OR actual_size_bytes > 0",
            name="ck_model_assets_actual_size",
        ),
    )

    quote_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("quote_requests.id", ondelete="CASCADE"), nullable=False
    )
    client_token: Mapped[UUID] = mapped_column(nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    declared_format: Mapped[ModelFormat] = mapped_column(
        Enum(
            ModelFormat,
            native_enum=False,
            values_callable=enum_values,
            length=16,
            validate_strings=True,
            create_constraint=True,
            name="ck_model_assets_format",
        ),
        nullable=False,
    )
    declared_content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    expected_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actual_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    claimed_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_sha256: Mapped[str | None] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    status: Mapped[ModelAssetStatus] = mapped_column(
        Enum(
            ModelAssetStatus,
            native_enum=False,
            values_callable=enum_values,
            length=32,
            validate_strings=True,
            create_constraint=True,
            name="ck_model_assets_status",
        ),
        default=ModelAssetStatus.PENDING_UPLOAD,
        server_default=ModelAssetStatus.PENDING_UPLOAD.value,
        nullable=False,
    )
    upload_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_code: Mapped[str | None] = mapped_column(String(64))
    storage_etag: Mapped[str | None] = mapped_column(Text)

    quote_request: Mapped[QuoteRequest] = relationship(back_populates="assets")
