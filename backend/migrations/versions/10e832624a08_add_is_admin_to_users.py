"""add is_admin to users

Revision ID: 10e832624a08
Revises: 3f7ce38788a1
Create Date: 2026-10-06 23:20:35.120245

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '10e832624a08'
down_revision: Union[str, None] = '3f7ce38788a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
