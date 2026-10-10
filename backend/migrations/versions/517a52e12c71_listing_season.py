"""Seasonal organization for flower listings.

Revision ID: 517a52e12c71
Revises: 317c692432df
"""

import sqlalchemy as sa
from alembic import op

revision = "517a52e12c71"
down_revision = "317c692432df"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("flower_listings", sa.Column("season", sa.String(length=20), server_default="", nullable=False))


def downgrade():
    op.drop_column("flower_listings", "season")
