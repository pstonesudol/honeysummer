"""Add bouquet invoice proposals.

Revision ID: f3b8a209cd17
Revises: 16ab07d4e561
"""
from alembic import op
import sqlalchemy as sa

revision = "f3b8a209cd17"
down_revision = "16ab07d4e561"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "bouquet_proposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inquiry_id", sa.Integer(), sa.ForeignKey("inquiries.id"), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("draft", sa.JSON(), nullable=False),
        sa.Column("history", sa.JSON(), nullable=False),
        sa.Column("activity", sa.JSON(), nullable=False),
        sa.Column("internal_notes", sa.Text(), nullable=False),
        sa.Column("stripe_customer_id", sa.String(255)),
        sa.Column("stripe_invoice_id", sa.String(255), unique=True),
        sa.Column("invoice_url", sa.Text(), nullable=False),
        sa.Column("invoice_number", sa.String(100), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("bouquet_proposals")
