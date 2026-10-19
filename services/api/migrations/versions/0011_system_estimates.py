"""Allow an audited system calculation without attributing it to a human owner."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_system_estimates"
down_revision: str = "0010_print_specifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("quote_estimates") as batch:
        batch.alter_column("created_by_user_id", existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    raise RuntimeError("Preserve system calculation attribution; use a reviewed forward fix.")
