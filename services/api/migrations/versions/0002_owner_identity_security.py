"""Add singleton owner, TOTP MFA, recovery codes, and authentication audit.

Revision ID: 0002_owner_identity_security
Revises: 0001_identity_foundation
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_owner_identity_security"
down_revision: str | None = "0001_identity_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


AUDIT_EVENT_TYPES = (
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


def upgrade() -> None:
    """Add owner and second-factor security state."""
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("owner_slot", sa.String(length=16), nullable=True))
    connection = op.get_bind()
    owner_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM users WHERE role = 'owner'")
    ).scalar_one()
    if owner_count > 1:
        raise RuntimeError("cannot migrate more than one pre-existing owner")
    connection.execute(
        sa.text("UPDATE users SET owner_slot = 'primary' WHERE role = 'owner'")
    )
    with op.batch_alter_table("users") as batch:
        batch.create_unique_constraint("uq_users_owner_slot", ["owner_slot"])
        batch.create_check_constraint(
            "ck_users_owner_slot",
            "(role = 'owner' AND owner_slot = 'primary') OR "
            "(role = 'buyer' AND owner_slot IS NULL)",
        )

    with op.batch_alter_table("refresh_sessions") as batch:
        batch.add_column(sa.Column("authenticated_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("mfa_authenticated_at", sa.DateTime(timezone=True), nullable=True)
        )
    op.execute(sa.text("UPDATE refresh_sessions SET authenticated_at = created_at"))
    with op.batch_alter_table("refresh_sessions") as batch:
        batch.alter_column(
            "authenticated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )

    with op.batch_alter_table("one_time_tokens") as batch:
        batch.drop_constraint("ck_one_time_tokens_purpose", type_="check")
        batch.create_check_constraint(
            "ck_one_time_tokens_purpose",
            "purpose IN ('verify_email', 'reset_password', 'mfa_login')",
        )

    op.create_table(
        "mfa_methods",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_counter", sa.BigInteger(), nullable=True),
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
        sa.CheckConstraint("kind IN ('totp')", name="ck_mfa_methods_kind"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )

    op.create_table(
        "mfa_recovery_codes",
        sa.Column("mfa_method_id", sa.Uuid(), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["mfa_method_id"], ["mfa_methods.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_digest"),
    )
    op.create_index(
        "ix_mfa_recovery_codes_method_unused",
        "mfa_recovery_codes",
        ["mfa_method_id", "used_at"],
        unique=False,
    )

    op.create_table(
        "audit_events",
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("target_user_id", sa.Uuid(), nullable=True),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            f"event_type IN ({', '.join(repr(value) for value in AUDIT_EVENT_TYPES)})",
            name="ck_audit_events_type",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("event_type", "actor_user_id", "target_user_id", "session_id", "occurred_at"):
        op.create_index(f"ix_audit_events_{column}", "audit_events", [column], unique=False)


def downgrade() -> None:
    """Remove owner security state without touching buyer identities."""
    op.drop_table("audit_events")
    op.drop_table("mfa_recovery_codes")
    op.drop_table("mfa_methods")
    with op.batch_alter_table("refresh_sessions") as batch:
        batch.drop_column("mfa_authenticated_at")
        batch.drop_column("authenticated_at")
    with op.batch_alter_table("one_time_tokens") as batch:
        batch.drop_constraint("ck_one_time_tokens_purpose", type_="check")
        batch.create_check_constraint(
            "ck_one_time_tokens_purpose",
            "purpose IN ('verify_email', 'reset_password')",
        )
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_owner_slot", type_="check")
        batch.drop_constraint("uq_users_owner_slot", type_="unique")
        batch.drop_column("owner_slot")
