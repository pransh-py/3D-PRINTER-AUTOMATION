"""Payment adapter evidence and recoverable Checkout binding (forward-fix only)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_payment_adapter"
down_revision: str = "0007_analysis_previews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("payment_intents") as batch:
        batch.add_column(sa.Column("provider_key_id", sa.String(100), nullable=True))
        batch.add_column(sa.Column("checkout_payment_id", sa.String(100), nullable=True))
        batch.add_column(sa.Column("last_reconciled_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("failure_code", sa.String(80), nullable=True))
    with op.batch_alter_table("payment_provider_events") as batch:
        batch.add_column(
            sa.Column("evidence_source", sa.String(16), nullable=False, server_default="webhook")
        )
        batch.add_column(
            sa.Column("api_authenticated_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.alter_column(
            "signature_validated_at", existing_type=sa.DateTime(timezone=True), nullable=True
        )
        batch.create_check_constraint(
            "ck_payment_events_authentication",
            "(evidence_source = 'webhook' AND signature_validated_at IS NOT NULL "
            "AND api_authenticated_at IS NULL) OR (evidence_source = 'api' "
            "AND api_authenticated_at IS NOT NULL AND signature_validated_at IS NULL)",
        )
    # Freeze historical values; never import the mutable current enum into migrations.
    audit_events = (
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
        "pricing.policy_created",
        "pricing.policy_activated",
        "pricing.estimate_created",
        "quote.issued",
        "quote.rejected",
        "quote.accepted",
        "payment.confirmed",
        "production.job_changed",
        "production.readiness_completed",
        "production.bridge_paired",
        "production.bridge_revoked",
        "production.print_authorized",
        "fulfillment.changed",
        "payment.checkout_created",
        "payment.checkout_returned",
        "payment.reconciled",
    )
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint("ck_audit_events_type", type_="check")
        batch.create_check_constraint(
            "ck_audit_events_type", f"event_type IN ({', '.join(repr(v) for v in audit_events)})"
        )


def downgrade() -> None:
    raise RuntimeError("Preserve financial evidence; use a reviewed forward fix.")
