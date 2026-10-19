"""Add versioned pricing policies and immutable estimates.

Revision ID: 0005_versioned_pricing
Revises: 0004_analysis_orchestration
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_versioned_pricing"
down_revision: str | None = "0004_analysis_orchestration"
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
    "analysis.run_queued",
    "analysis.run_started",
    "analysis.run_awaiting_profile",
    "analysis.run_succeeded",
    "analysis.run_failed",
)
PRICING_AUDIT_EVENTS = (
    "pricing.policy_created",
    "pricing.policy_activated",
    "pricing.estimate_created",
)


def _event_check(values: tuple[str, ...]) -> str:
    return f"event_type IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    """Create immutable rate-card versions and estimate snapshots."""
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint("ck_audit_events_type", type_="check")
        batch.create_check_constraint(
            "ck_audit_events_type",
            _event_check(PREVIOUS_AUDIT_EVENTS + PRICING_AUDIT_EVENTS),
        )

    with op.batch_alter_table("analysis_runs") as batch:
        batch.add_column(sa.Column("material_code", sa.String(length=32), nullable=True))

    op.create_table(
        "pricing_policies",
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="INR", nullable=False),
        sa.Column("machine_rate_paise_per_hour", sa.BigInteger(), nullable=False),
        sa.Column("setup_fee_paise", sa.BigInteger(), nullable=False),
        sa.Column("minimum_order_paise", sa.BigInteger(), nullable=False),
        sa.Column("contingency_bps", sa.Integer(), nullable=False),
        sa.Column("tax_bps", sa.Integer(), nullable=False),
        sa.Column("estimate_validity_hours", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("activated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version >= 1", name="ck_pricing_policies_version"),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'retired')",
            name="ck_pricing_policies_status",
        ),
        sa.CheckConstraint("currency = 'INR'", name="ck_pricing_policies_currency"),
        sa.CheckConstraint(
            "machine_rate_paise_per_hour >= 0", name="ck_pricing_policies_machine_rate"
        ),
        sa.CheckConstraint("setup_fee_paise >= 0", name="ck_pricing_policies_setup_fee"),
        sa.CheckConstraint(
            "minimum_order_paise >= 0", name="ck_pricing_policies_minimum_order"
        ),
        sa.CheckConstraint(
            "contingency_bps BETWEEN 0 AND 10000", name="ck_pricing_policies_contingency"
        ),
        sa.CheckConstraint("tax_bps BETWEEN 0 AND 10000", name="ck_pricing_policies_tax"),
        sa.CheckConstraint(
            "estimate_validity_hours BETWEEN 1 AND 720", name="ck_pricing_policies_validity"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activated_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version"),
    )
    op.create_index("ix_pricing_policies_status", "pricing_policies", ["status"])
    op.create_index(
        "uq_pricing_policies_one_active",
        "pricing_policies",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "material_rates",
        sa.Column("pricing_policy_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("rate_paise_per_gram", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("rate_paise_per_gram >= 0", name="ck_material_rates_rate"),
        sa.ForeignKeyConstraint(
            ["pricing_policy_id"], ["pricing_policies.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pricing_policy_id", "code", name="uq_material_rates_policy_code"),
    )

    op.create_table(
        "quote_estimates",
        sa.Column("quote_request_id", sa.Uuid(), nullable=False),
        sa.Column("client_token", sa.Uuid(), nullable=False),
        sa.Column("quote_request_version", sa.Integer(), nullable=False),
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("pricing_policy_id", sa.Uuid(), nullable=False),
        sa.Column("material_rate_id", sa.Uuid(), nullable=False),
        sa.Column("calculation_version", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("material_code", sa.String(length=32), nullable=False),
        sa.Column("material_name", sa.String(length=80), nullable=False),
        sa.Column("filament_mg", sa.BigInteger(), nullable=False),
        sa.Column("duration_seconds", sa.BigInteger(), nullable=False),
        sa.Column("material_rate_paise_per_gram", sa.BigInteger(), nullable=False),
        sa.Column("machine_rate_paise_per_hour", sa.BigInteger(), nullable=False),
        sa.Column("setup_paise", sa.BigInteger(), nullable=False),
        sa.Column("contingency_bps", sa.Integer(), nullable=False),
        sa.Column("minimum_order_paise", sa.BigInteger(), nullable=False),
        sa.Column("tax_bps", sa.Integer(), nullable=False),
        sa.Column("material_paise", sa.BigInteger(), nullable=False),
        sa.Column("machine_paise", sa.BigInteger(), nullable=False),
        sa.Column("contingency_paise", sa.BigInteger(), nullable=False),
        sa.Column("minimum_adjustment_paise", sa.BigInteger(), nullable=False),
        sa.Column("pre_tax_paise", sa.BigInteger(), nullable=False),
        sa.Column("tax_paise", sa.BigInteger(), nullable=False),
        sa.Column("total_paise", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("quote_request_version >= 1", name="ck_quote_estimates_version"),
        sa.CheckConstraint("currency = 'INR'", name="ck_quote_estimates_currency"),
        sa.CheckConstraint("filament_mg >= 0", name="ck_quote_estimates_filament"),
        sa.CheckConstraint("duration_seconds >= 0", name="ck_quote_estimates_duration"),
        sa.CheckConstraint(
            "material_rate_paise_per_gram >= 0",
            name="ck_quote_estimates_material_rate",
        ),
        sa.CheckConstraint(
            "machine_rate_paise_per_hour >= 0",
            name="ck_quote_estimates_machine_rate",
        ),
        sa.CheckConstraint("setup_paise >= 0", name="ck_quote_estimates_setup"),
        sa.CheckConstraint(
            "contingency_bps BETWEEN 0 AND 10000",
            name="ck_quote_estimates_contingency_bps",
        ),
        sa.CheckConstraint(
            "minimum_order_paise >= 0",
            name="ck_quote_estimates_minimum_order",
        ),
        sa.CheckConstraint(
            "tax_bps BETWEEN 0 AND 10000",
            name="ck_quote_estimates_tax_bps",
        ),
        sa.CheckConstraint("material_paise >= 0", name="ck_quote_estimates_material"),
        sa.CheckConstraint("machine_paise >= 0", name="ck_quote_estimates_machine"),
        sa.CheckConstraint(
            "contingency_paise >= 0",
            name="ck_quote_estimates_contingency",
        ),
        sa.CheckConstraint(
            "minimum_adjustment_paise >= 0",
            name="ck_quote_estimates_minimum_adjustment",
        ),
        sa.CheckConstraint("pre_tax_paise >= 0", name="ck_quote_estimates_pre_tax"),
        sa.CheckConstraint("tax_paise >= 0", name="ck_quote_estimates_tax"),
        sa.CheckConstraint("total_paise >= 0", name="ck_quote_estimates_total"),
        sa.ForeignKeyConstraint(["quote_request_id"], ["quote_requests.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["pricing_policy_id"], ["pricing_policies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["material_rate_id"], ["material_rates.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "quote_request_id",
            "quote_request_version",
            "pricing_policy_id",
            "material_rate_id",
            name="uq_quote_estimates_inputs",
        ),
        sa.UniqueConstraint(
            "quote_request_id",
            "client_token",
            name="uq_quote_estimates_request_client",
        ),
    )
    op.create_index(
        "ix_quote_estimates_request_created",
        "quote_estimates",
        ["quote_request_id", "created_at"],
    )


def downgrade() -> None:
    """Remove pricing data and restore the prior audit constraint."""
    op.drop_table("quote_estimates")
    op.drop_table("material_rates")
    op.drop_table("pricing_policies")
    with op.batch_alter_table("analysis_runs") as batch:
        batch.drop_column("material_code")
    op.execute("DELETE FROM audit_events WHERE " + _event_check(PRICING_AUDIT_EVENTS))
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint("ck_audit_events_type", type_="check")
        batch.create_check_constraint(
            "ck_audit_events_type",
            _event_check(PREVIOUS_AUDIT_EVENTS),
        )
