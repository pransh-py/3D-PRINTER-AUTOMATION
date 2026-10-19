"""Capture the exact selected print offering without rewriting historical orders."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_print_specifications"
down_revision: str = "0009_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("quote_requests", sa.Column("print_specification", sa.JSON(), nullable=True))
    op.add_column("quotes", sa.Column("print_specification", sa.JSON(), nullable=True))
    op.add_column("analysis_runs", sa.Column("print_preset_code", sa.String(32), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Preserve quoted print specifications; use a reviewed forward fix.")
