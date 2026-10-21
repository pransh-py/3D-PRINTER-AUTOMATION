"""Phone-only buyer identity, bounded challenges and no owner phone login."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_phone_identity"
down_revision: str = "0012_model_review_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.alter_column("email", existing_type=sa.String(320), nullable=True)
        batch.alter_column("password_hash", existing_type=sa.Text(), nullable=True)
        batch.add_column(sa.Column("phone_e164", sa.String(16)))
        batch.add_column(sa.Column("phone_verified_at", sa.DateTime(timezone=True)))
        batch.create_index("ix_users_phone_e164", ["phone_e164"], unique=True)
        batch.create_check_constraint(
            "ck_users_credentials",
            "(email IS NOT NULL AND password_hash IS NOT NULL) OR phone_e164 IS NOT NULL",
        )
        batch.create_check_constraint(
            "ck_users_owner_email_only",
            "role <> 'owner' OR (email IS NOT NULL AND password_hash IS NOT NULL "
            "AND phone_e164 IS NULL)",
        )
        batch.create_check_constraint(
            "ck_users_email_verified", "email_verified_at IS NULL OR email IS NOT NULL"
        )
        batch.create_check_constraint(
            "ck_users_phone_verified",
            "(phone_e164 IS NULL AND phone_verified_at IS NULL) OR "
            "(phone_e164 IS NOT NULL AND phone_verified_at IS NOT NULL)",
        )
        batch.create_check_constraint(
            "ck_users_phone_format",
            "phone_e164 IS NULL OR (length(phone_e164) = 13 AND substr(phone_e164, 1, 3) = '+91')",
        )
    op.create_table(
        "phone_otp_challenges",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("challenge_digest", sa.String(64), unique=True, nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("phone_e164", sa.String(16), nullable=False),
        sa.Column("display_name", sa.String(100)),
        sa.Column("code_digest", sa.String(64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("purpose IN ('signup','login')", name="ck_phone_otp_challenges_purpose"),
        sa.CheckConstraint(
            "attempt_count BETWEEN 0 AND 5", name="ck_phone_otp_challenges_attempts"
        ),
    )
    op.create_index("ix_phone_otp_challenges_phone_e164", "phone_otp_challenges", ["phone_e164"])
    op.create_index("ix_phone_otp_challenges_expires_at", "phone_otp_challenges", ["expires_at"])
    op.create_index(
        "uq_phone_otp_active_phone",
        "phone_otp_challenges",
        ["phone_e164"],
        unique=True,
        sqlite_where=sa.text("consumed_at IS NULL"),
        postgresql_where=sa.text("consumed_at IS NULL"),
    )


def downgrade() -> None:
    raise RuntimeError("Preserve verified phone identities; use a reviewed forward fix.")
