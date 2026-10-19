"""Permit a non-secret audit record for owner access to validated private models."""

from collections.abc import Sequence

from alembic import op

revision: str = "0012_model_review_audit"
down_revision: str = "0011_system_estimates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Freeze the values in this revision; do not import the evolving application enum.
    values = (
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
        "quote.model_source_accessed",
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
        "notification.retry_requested",
    )
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint("ck_audit_events_type", type_="check")
        batch.create_check_constraint(
            "ck_audit_events_type", f"event_type IN ({', '.join(repr(value) for value in values)})"
        )


def downgrade() -> None:
    raise RuntimeError("Preserve private-model access evidence; use a reviewed forward fix.")
