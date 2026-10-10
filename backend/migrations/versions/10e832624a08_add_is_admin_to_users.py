"""add is_admin to users

Revision ID: 10e832624a08
Revises: 3f7ce38788a1
Create Date: 2026-10-06 23:20:35.120245

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "10e832624a08"
down_revision: str | None = "3f7ce38788a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
