"""Versioned model-analysis evidence and transactional outbox persistence."""

from __future__ import annotations

from datetime import datetime
from enum import Enum as PythonEnum
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from xxx_api.domain.quotes import AnalysisAssetStatus, AnalysisRunStatus, ModelFormat
from xxx_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def enum_values(enum_class: type[PythonEnum]) -> list[str]:
    """Persist stable enum values rather than Python member names."""
    return [str(member.value) for member in enum_class]


class AnalysisRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable-input analysis attempt for one submitted quote version."""

    __tablename__ = "analysis_runs"
    __table_args__ = (
        UniqueConstraint(
            "quote_request_id",
            "request_version",
            name="uq_analysis_runs_request_version",
        ),
        CheckConstraint("request_version >= 1", name="ck_analysis_runs_request_version"),
        CheckConstraint("attempt_count >= 0", name="ck_analysis_runs_attempt_count"),
        CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_analysis_runs_lease_pair",
        ),
        Index("ix_analysis_runs_status_queued", "status", "queued_at"),
    )

    quote_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("quote_requests.id", ondelete="CASCADE"), nullable=False
    )
    request_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[AnalysisRunStatus] = mapped_column(
        Enum(
            AnalysisRunStatus,
            native_enum=False,
            values_callable=enum_values,
            length=32,
            validate_strings=True,
            create_constraint=True,
            name="ck_analysis_runs_status",
        ),
        default=AnalysisRunStatus.QUEUED,
        server_default=AnalysisRunStatus.QUEUED.value,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lease_token: Mapped[UUID | None]
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    validator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    slicer_name: Mapped[str | None] = mapped_column(String(64))
    slicer_version: Mapped[str | None] = mapped_column(String(64))
    profile_sha256: Mapped[str | None] = mapped_column(String(64))
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(64))

    quote_request: Mapped[QuoteRequest] = relationship(back_populates="analysis_runs")
    asset_results: Mapped[list[AnalysisAssetResult]] = relationship(
        back_populates="analysis_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AnalysisAssetResult.created_at",
    )


class AnalysisAssetResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Validated, bounded evidence for one source asset in one run."""

    __tablename__ = "analysis_asset_results"
    __table_args__ = (
        UniqueConstraint(
            "analysis_run_id",
            "model_asset_id",
            name="uq_analysis_asset_results_run_asset",
        ),
        CheckConstraint(
            "dimension_x_um IS NULL OR dimension_x_um >= 0",
            name="ck_analysis_asset_dimension_x",
        ),
        CheckConstraint(
            "dimension_y_um IS NULL OR dimension_y_um >= 0",
            name="ck_analysis_asset_dimension_y",
        ),
        CheckConstraint(
            "dimension_z_um IS NULL OR dimension_z_um >= 0",
            name="ck_analysis_asset_dimension_z",
        ),
        CheckConstraint(
            "triangle_count IS NULL OR triangle_count >= 0",
            name="ck_analysis_asset_triangle_count",
        ),
        CheckConstraint(
            "object_count IS NULL OR object_count >= 0",
            name="ck_analysis_asset_object_count",
        ),
        CheckConstraint(
            "filament_mg IS NULL OR filament_mg >= 0",
            name="ck_analysis_asset_filament",
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="ck_analysis_asset_duration",
        ),
        Index("ix_analysis_asset_results_asset", "model_asset_id"),
    )

    analysis_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    model_asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("model_assets.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[AnalysisAssetStatus] = mapped_column(
        Enum(
            AnalysisAssetStatus,
            native_enum=False,
            values_callable=enum_values,
            length=32,
            validate_strings=True,
            create_constraint=True,
            name="ck_analysis_asset_results_status",
        ),
        nullable=False,
    )
    detected_format: Mapped[ModelFormat | None] = mapped_column(
        Enum(
            ModelFormat,
            native_enum=False,
            values_callable=enum_values,
            length=16,
            validate_strings=True,
            create_constraint=True,
            name="ck_analysis_asset_results_format",
        )
    )
    verified_sha256: Mapped[str | None] = mapped_column(String(64))
    dimension_x_um: Mapped[int | None] = mapped_column(BigInteger)
    dimension_y_um: Mapped[int | None] = mapped_column(BigInteger)
    dimension_z_um: Mapped[int | None] = mapped_column(BigInteger)
    triangle_count: Mapped[int | None] = mapped_column(BigInteger)
    object_count: Mapped[int | None] = mapped_column(Integer)
    fits_build_volume: Mapped[bool | None] = mapped_column(Boolean)
    warning_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    filament_mg: Mapped[int | None] = mapped_column(BigInteger)
    duration_seconds: Mapped[int | None] = mapped_column(BigInteger)
    artifact_storage_key: Mapped[str | None] = mapped_column(String(512))
    artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(64))

    analysis_run: Mapped[AnalysisRun] = relationship(back_populates="asset_results")
    model_asset: Mapped[ModelAsset] = relationship()


class OutboxEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Database-authoritative event awaiting at-least-once publication."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="ck_outbox_events_attempt_count"),
        Index("ix_outbox_events_unpublished", "published_at", "available_at"),
    )

    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error_code: Mapped[str | None] = mapped_column(String(64))


from xxx_api.models.quotes import ModelAsset, QuoteRequest  # noqa: E402
