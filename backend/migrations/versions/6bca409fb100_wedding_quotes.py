"""Wedding quotes and independently reconciled invoice installments.

Revision ID: 6bca409fb100
Revises: 59d047ca3a21
"""
from alembic import op
import sqlalchemy as sa

revision = "6bca409fb100"
down_revision = "59d047ca3a21"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("wedding_quotes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inquiry_id", sa.Integer(), sa.ForeignKey("inquiries.id"), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("draft", sa.JSON(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("payment_mode", sa.String(20), nullable=False),
        sa.Column("deposit_cents", sa.Integer(), nullable=False),
        sa.Column("stripe_customer_id", sa.String(255)),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), unique=True),
        sa.Column("activity", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("wedding_invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("quote_id", sa.Integer(), sa.ForeignKey("wedding_quotes.id"), nullable=False),
        sa.Column("step", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("stripe_invoice_id", sa.String(255), unique=True),
        sa.Column("hosted_url", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True)))
    op.create_unique_constraint("uq_wedding_invoice_step", "wedding_invoices", ["quote_id", "step"])
    op.create_index("ix_wedding_invoices_quote_id", "wedding_invoices", ["quote_id"])


def downgrade():
    op.drop_index("ix_wedding_invoices_quote_id", table_name="wedding_invoices")
    op.drop_table("wedding_invoices")
    op.drop_table("wedding_quotes")
