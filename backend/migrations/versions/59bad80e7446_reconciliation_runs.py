"""Persist reconciliation run results.

Revision ID: 59bad80e7446
Revises: 517a52e12c71
"""

import sqlalchemy as sa
from alembic import op

revision = "59bad80e7446"
down_revision = "517a52e12c71"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "reconciliation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied", sa.Boolean(), nullable=False),
        sa.Column("full", sa.Boolean(), nullable=False),
        sa.Column("findings", sa.JSON(), nullable=False),
        sa.Column("finding_count", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("reconciliation_runs")
