"""Add versioned analysis evidence and transactional outbox.

Revision ID: 0004_analysis_orchestration
Revises: 0003_quote_upload_intake
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_analysis_orchestration"
down_revision: str | None = "0003_quote_upload_intake"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PREVIOUS_AUDIT_EVENTS = (
    "identity.buyer_registered",
    "identity.email_verified",
    "identity.session_created",
    "identity.session_revoked",
    "identity.refresh_reuse_detected",
    "identity.password_reset",
    "identity.owner_provisioned",
    "identity.owner_mfa_challenge_issued",
    "identity.owner_mfa_authenticated",
    "identity.owner_mfa_enrollment_started",
    "identity.owner_mfa_enabled",
    "identity.owner_mfa_reset",
    "quote.request_created",
    "quote.model_upload_issued",
    "quote.model_upload_completed",
    "quote.model_upload_rejected",
    "quote.request_submitted",
)
ANALYSIS_AUDIT_EVENTS = (
    "analysis.run_queued",
    "analysis.run_started",
    "analysis.run_awaiting_profile",
    "analysis.run_succeeded",
    "analysis.run_failed",
)


def _event_check(values: tuple[str, ...]) -> str:
    return f"event_type IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    """Create durable analysis runs, asset evidence, and an outbox."""
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint("ck_audit_events_type", type_="check")
        batch.create_check_constraint(
            "ck_audit_events_type",
            _event_check(PREVIOUS_AUDIT_EVENTS + ANALYSIS_AUDIT_EVENTS),
        )

    with op.batch_alter_table("quote_requests") as batch:
        batch.drop_constraint("ck_quote_requests_status", type_="check")
        batch.create_check_constraint(
            "ck_quote_requests_status",
            "status IN ('draft', 'analyzing', 'analysis_failed', 'analysis_ready', "
            "'estimate_ready', 'owner_review', 'quoted', 'rejected')",
        )

    op.create_table(
        "analysis_runs",
        sa.Column("quote_request_id", sa.Uuid(), nullable=False),
        sa.Column("request_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("validator_version", sa.String(length=64), nullable=False),
        sa.Column("slicer_name", sa.String(length=64), nullable=True),
        sa.Column("slicer_version", sa.String(length=64), nullable=True),
        sa.Column("profile_sha256", sa.String(length=64), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'awaiting_profile', 'succeeded', 'failed')",
            name="ck_analysis_runs_status",
        ),
        sa.CheckConstraint("request_version >= 1", name="ck_analysis_runs_request_version"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_analysis_runs_attempt_count"),
        sa.CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_analysis_runs_lease_pair",
        ),
        sa.ForeignKeyConstraint(
            ["quote_request_id"],
            ["quote_requests.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "quote_request_id",
            "request_version",
            name="uq_analysis_runs_request_version",
        ),
    )
    op.create_index(
        "ix_analysis_runs_status_queued",
        "analysis_runs",
        ["status", "queued_at"],
        unique=False,
    )

    op.create_table(
        "analysis_asset_results",
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("model_asset_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("detected_format", sa.String(length=16), nullable=True),
        sa.Column("verified_sha256", sa.String(length=64), nullable=True),
        sa.Column("dimension_x_um", sa.BigInteger(), nullable=True),
        sa.Column("dimension_y_um", sa.BigInteger(), nullable=True),
        sa.Column("dimension_z_um", sa.BigInteger(), nullable=True),
        sa.Column("triangle_count", sa.BigInteger(), nullable=True),
        sa.Column("object_count", sa.Integer(), nullable=True),
        sa.Column("fits_build_volume", sa.Boolean(), nullable=True),
        sa.Column("warning_codes", sa.JSON(), nullable=False),
        sa.Column("filament_mg", sa.BigInteger(), nullable=True),
        sa.Column("duration_seconds", sa.BigInteger(), nullable=True),
        sa.Column("artifact_storage_key", sa.String(length=512), nullable=True),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('validated', 'awaiting_profile', 'sliced', 'rejected')",
            name="ck_analysis_asset_results_status",
        ),
        sa.CheckConstraint(
            "detected_format IS NULL OR detected_format IN ('stl', '3mf', 'obj', 'step')",
            name="ck_analysis_asset_results_format",
        ),
        sa.CheckConstraint(
            "dimension_x_um IS NULL OR dimension_x_um >= 0",
            name="ck_analysis_asset_dimension_x",
        ),
        sa.CheckConstraint(
            "dimension_y_um IS NULL OR dimension_y_um >= 0",
            name="ck_analysis_asset_dimension_y",
        ),
        sa.CheckConstraint(
            "dimension_z_um IS NULL OR dimension_z_um >= 0",
            name="ck_analysis_asset_dimension_z",
        ),
        sa.CheckConstraint(
            "triangle_count IS NULL OR triangle_count >= 0",
            name="ck_analysis_asset_triangle_count",
        ),
        sa.CheckConstraint(
            "object_count IS NULL OR object_count >= 0",
            name="ck_analysis_asset_object_count",
        ),
        sa.CheckConstraint(
            "filament_mg IS NULL OR filament_mg >= 0",
            name="ck_analysis_asset_filament",
        ),
        sa.CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="ck_analysis_asset_duration",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["analysis_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["model_asset_id"],
            ["model_assets.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analysis_run_id",
            "model_asset_id",
            name="uq_analysis_asset_results_run_asset",
        ),
    )
    op.create_index(
        "ix_analysis_asset_results_asset",
        "analysis_asset_results",
        ["model_asset_id"],
        unique=False,
    )

    op.create_table(
        "outbox_events",
        sa.Column("topic", sa.String(length=64), nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_outbox_events_attempt_count"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_outbox_events_unpublished",
        "outbox_events",
        ["published_at", "available_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove analysis orchestration and restore the prior state constraints."""
    op.drop_table("outbox_events")
    op.drop_table("analysis_asset_results")
    op.drop_table("analysis_runs")
    op.execute(
        "UPDATE quote_requests SET status = 'analysis_failed' "
        "WHERE status = 'analysis_ready'"
    )
    op.execute(
        "DELETE FROM audit_events WHERE "
        + _event_check(ANALYSIS_AUDIT_EVENTS)
    )

    with op.batch_alter_table("quote_requests") as batch:
        batch.drop_constraint("ck_quote_requests_status", type_="check")
        batch.create_check_constraint(
            "ck_quote_requests_status",
            "status IN ('draft', 'analyzing', 'analysis_failed', 'estimate_ready', "
            "'owner_review', 'quoted', 'rejected')",
        )

    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint("ck_audit_events_type", type_="check")
        batch.create_check_constraint(
            "ck_audit_events_type",
            _event_check(PREVIOUS_AUDIT_EVENTS),
        )
