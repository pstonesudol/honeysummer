"""Itemized installment schedule on wedding quotes.

Revision ID: b538d903ec41
Revises: 7df628ea12bb
"""

import sqlalchemy as sa
from alembic import op

revision = "b538d903ec41"
down_revision = "7df628ea12bb"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("wedding_quotes", sa.Column("installments", sa.JSON(), nullable=False, server_default="[]"))


def downgrade():
    op.drop_column("wedding_quotes", "installments")
