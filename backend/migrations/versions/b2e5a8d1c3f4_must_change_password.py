"""Add must_change_password for administrator-set temporary passwords.

Revision ID: b2e5a8d1c3f4
Revises: a1d4f7c9b2e3
"""

import sqlalchemy as sa
from alembic import op

revision = "b2e5a8d1c3f4"
down_revision = "a1d4f7c9b2e3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("users", "must_change_password")
