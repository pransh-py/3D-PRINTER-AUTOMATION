"""Add private quote-request and model-upload intake.

Revision ID: 0003_quote_upload_intake
Revises: 0002_owner_identity_security
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_quote_upload_intake"
down_revision: str | None = "0002_owner_identity_security"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IDENTITY_AUDIT_EVENTS = (
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
)
QUOTE_AUDIT_EVENTS = (
    "quote.request_created",
    "quote.model_upload_issued",
    "quote.model_upload_completed",
    "quote.model_upload_rejected",
    "quote.request_submitted",
)


def _event_check(values: tuple[str, ...]) -> str:
    return f"event_type IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    """Create buyer-owned quote requests and quarantined source-object evidence."""
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint("ck_audit_events_type", type_="check")
        batch.create_check_constraint(
            "ck_audit_events_type",
            _event_check(IDENTITY_AUDIT_EVENTS + QUOTE_AUDIT_EVENTS),
        )

    op.create_table(
        "quote_requests",
        sa.Column("buyer_id", sa.Uuid(), nullable=False),
        sa.Column("client_token", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('draft', 'analyzing', 'analysis_failed', 'estimate_ready', "
            "'owner_review', 'quoted', 'rejected')",
            name="ck_quote_requests_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_quote_requests_version_positive"),
        sa.ForeignKeyConstraint(["buyer_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("buyer_id", "client_token", name="uq_quote_requests_buyer_client"),
    )
    op.create_index(
        "ix_quote_requests_buyer_created",
        "quote_requests",
        ["buyer_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_quote_requests_status_created",
        "quote_requests",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "model_assets",
        sa.Column("quote_request_id", sa.Uuid(), nullable=False),
        sa.Column("client_token", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("declared_format", sa.String(length=16), nullable=False),
        sa.Column("declared_content_type", sa.String(length=100), nullable=False),
        sa.Column("expected_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("actual_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("claimed_sha256", sa.String(length=64), nullable=False),
        sa.Column("verified_sha256", sa.String(length=64), nullable=True),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="pending_upload",
            nullable=False,
        ),
        sa.Column("upload_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_code", sa.String(length=64), nullable=True),
        sa.Column("storage_etag", sa.Text(), nullable=True),
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
            "status IN ('pending_upload', 'quarantined', 'validating', 'validated', 'rejected')",
            name="ck_model_assets_status",
        ),
        sa.CheckConstraint(
            "declared_format IN ('stl', '3mf', 'obj', 'step')",
            name="ck_model_assets_format",
        ),
        sa.CheckConstraint("expected_size_bytes > 0", name="ck_model_assets_expected_size"),
        sa.CheckConstraint(
            "actual_size_bytes IS NULL OR actual_size_bytes > 0",
            name="ck_model_assets_actual_size",
        ),
        sa.ForeignKeyConstraint(
            ["quote_request_id"],
            ["quote_requests.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
        sa.UniqueConstraint(
            "quote_request_id",
            "client_token",
            name="uq_model_assets_request_client",
        ),
    )
    op.create_index(
        "ix_model_assets_request_status",
        "model_assets",
        ["quote_request_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    """Remove model intake while preserving identity audit constraints."""
    op.drop_table("model_assets")
    op.drop_table("quote_requests")
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint("ck_audit_events_type", type_="check")
        batch.create_check_constraint(
            "ck_audit_events_type",
            _event_check(IDENTITY_AUDIT_EVENTS),
        )
