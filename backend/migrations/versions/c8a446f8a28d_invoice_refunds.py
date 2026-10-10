"""Track Stripe invoice refunds independently of Checkout orders.

Revision ID: c8a446f8a28d
Revises: 7e18b051c429
"""

import sqlalchemy as sa
from alembic import op

revision = "c8a446f8a28d"
down_revision = "7e18b051c429"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "invoice_refunds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("wedding_invoice_id", sa.Integer(), sa.ForeignKey("wedding_invoices.id"), nullable=True),
        sa.Column("proposal_id", sa.Integer(), sa.ForeignKey("bouquet_proposals.id"), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("payment_intent_id", sa.String(length=255), nullable=False),
        sa.Column("stripe_refund_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=36), nullable=False, unique=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_cents > 0", name="invoice_refund_amount_positive"),
        sa.CheckConstraint(
            "(wedding_invoice_id IS NULL) != (proposal_id IS NULL)", name="invoice_refund_single_source"
        ),
    )
    op.create_index("ix_invoice_refunds_wedding_invoice_id", "invoice_refunds", ["wedding_invoice_id"])
    op.create_index("ix_invoice_refunds_proposal_id", "invoice_refunds", ["proposal_id"])


def downgrade():
    op.drop_index("ix_invoice_refunds_proposal_id", table_name="invoice_refunds")
    op.drop_index("ix_invoice_refunds_wedding_invoice_id", table_name="invoice_refunds")
    op.drop_table("invoice_refunds")
