"""Structured owner fulfillment and low-stock alerts.

Revision ID: 73ae28c0b912
Revises: f3b8a209cd17
"""

import sqlalchemy as sa
from alembic import op

revision = "73ae28c0b912"
down_revision = "f3b8a209cd17"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("flower_listings", sa.Column("low_stock_threshold", sa.Integer(), nullable=False, server_default="5"))
    op.add_column("orders", sa.Column("internal_notes", sa.Text(), nullable=False, server_default=""))
    op.add_column("orders", sa.Column("fulfillment_date", sa.Date(), nullable=True))
    op.add_column("orders", sa.Column("fulfillment_time", sa.Time(), nullable=True))
    op.add_column("orders", sa.Column("fulfillment_state", sa.String(20), nullable=False, server_default="new"))
    op.add_column("orders", sa.Column("activity", sa.JSON(), nullable=False, server_default="[]"))
    op.execute("UPDATE orders SET fulfillment_state = 'completed' WHERE fulfilled_at IS NOT NULL")
    op.create_check_constraint("flower_low_stock_threshold_nonnegative", "flower_listings", "low_stock_threshold >= 0")
    op.create_check_constraint(
        "order_fulfillment_state_valid", "orders", "fulfillment_state IN ('new', 'preparing', 'ready', 'completed')"
    )
    op.create_index("ix_orders_fulfillment_date", "orders", ["fulfillment_date"])


def downgrade():
    op.drop_index("ix_orders_fulfillment_date", table_name="orders")
    op.drop_constraint("order_fulfillment_state_valid", "orders", type_="check")
    op.drop_constraint("flower_low_stock_threshold_nonnegative", "flower_listings", type_="check")
    for column in ("activity", "fulfillment_state", "fulfillment_time", "fulfillment_date", "internal_notes"):
        op.drop_column("orders", column)
    op.drop_column("flower_listings", "low_stock_threshold")
