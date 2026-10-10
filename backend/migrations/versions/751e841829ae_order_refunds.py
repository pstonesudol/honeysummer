"""Audited payment refunds, separate from inventory returns.

Revision ID: 751e841829ae
Revises: b538d903ec41
"""

import sqlalchemy as sa
from alembic import op

revision = "751e841829ae"
down_revision = "b538d903ec41"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "order_refunds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reference", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=36), nullable=False, unique=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_cents > 0", name="order_refund_amount_positive"),
    )
    op.create_index("ix_order_refunds_order_id", "order_refunds", ["order_id"])


def downgrade():
    op.drop_index("ix_order_refunds_order_id", table_name="order_refunds")
    op.drop_table("order_refunds")
