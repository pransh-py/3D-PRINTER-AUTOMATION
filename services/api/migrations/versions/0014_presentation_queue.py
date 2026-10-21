"""Add an explicitly free presentation queue without changing commercial records."""

import sqlalchemy as sa
from alembic import op

revision = "0014_presentation_queue"
down_revision = "0013_phone_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "presentation_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "quote_request_id",
            sa.Uuid(),
            sa.ForeignKey("quote_requests.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("buyer_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("estimate_id", sa.Uuid(), sa.ForeignKey("quote_estimates.id"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("approved_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("authorization_id", sa.Uuid(), unique=True),
        sa.Column("bridge_id", sa.Uuid(), sa.ForeignKey("bridge_installations.id")),
        sa.Column("printer_filename", sa.String(96)),
        sa.Column("dispatch_sha256", sa.String(64)),
        sa.Column("progress_bps", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_presentation_version"),
        sa.CheckConstraint(
            "status IN ('waiting','approved','claimed','starting','printing','completed',"
            "'needs_attention','rejected','cancelled','stopped','refused')",
            name="ck_presentation_status",
        ),
    )
    op.create_index("ix_presentation_fifo", "presentation_entries", ["status", "approved_at", "id"])
    table = op.create_table(
        "presentation_station",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("active_entry_id", sa.Uuid(), sa.ForeignKey("presentation_entries.id")),
        sa.Column("clear_entry_id", sa.Uuid(), sa.ForeignKey("presentation_entries.id")),
        sa.Column("cleared_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("id = 1 AND version > 0", name="ck_presentation_singleton"),
    )
    op.bulk_insert(table, [{"id": 1, "version": 1, "state": "offline"}])


def downgrade():
    raise RuntimeError("Preserve presentation admissions and physical-attempt evidence.")
