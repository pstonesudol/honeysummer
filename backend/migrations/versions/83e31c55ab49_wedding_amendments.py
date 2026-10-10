"""Immutable revised wedding agreements after partial invoice refunds.

Revision ID: 83e31c55ab49
Revises: d64be6148b53
"""
from alembic import op
import sqlalchemy as sa

revision = "83e31c55ab49"
down_revision = "d64be6148b53"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("wedding_quotes", sa.Column("amendments", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("wedding_quotes", sa.Column("amendment_due_date", sa.Date(), nullable=True))


def downgrade():
    # Never downgrade an account that has already created amended invoices.
    op.drop_column("wedding_quotes", "amendment_due_date")
    op.drop_column("wedding_quotes", "amendments")
