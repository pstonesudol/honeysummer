"""Retain deleted operator accounts for historical references without login access."""

import sqlalchemy as sa
from alembic import op

revision = "d4a7b0c3e6f9"
down_revision = "c3f6a9b2d5e8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("users", "deleted_at")
