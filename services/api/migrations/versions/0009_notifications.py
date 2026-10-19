"""Private, fenced workflow notice delivery (forward-fix only)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_notifications"
down_revision: str = "0008_payment_adapter"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "outbox_event_id",
            sa.Uuid(),
            sa.ForeignKey("outbox_events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("recipient_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("channel", sa.String(16), nullable=False, server_default="email"),
        sa.Column("template_code", sa.String(64), nullable=False),
        sa.Column("template_version", sa.String(16), nullable=False, server_default="1"),
        sa.Column("destination_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("provider_message_id", sa.String(255)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "outbox_event_id",
            "recipient_user_id",
            "template_code",
            name="uq_notifications_event_recipient_template",
        ),
        sa.CheckConstraint("channel = 'email'", name="ck_notifications_channel"),
        sa.CheckConstraint(
            "status IN ('pending','sent','failed','dead_lettered')", name="ck_notifications_status"
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_notifications_attempt_count"),
        sa.CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_notifications_lease_pair",
        ),
    )
    op.create_index("ix_notifications_delivery", "notifications", ["status", "available_at"])
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
            "ck_audit_events_type", f"event_type IN ({', '.join(repr(v) for v in values)})"
        )


def downgrade() -> None:
    raise RuntimeError("Preserve delivery and audit evidence; use a reviewed forward fix.")
