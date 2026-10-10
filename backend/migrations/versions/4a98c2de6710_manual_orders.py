"""Manual payment provenance and custom order lines.

Revision ID: 4a98c2de6710
Revises: 73ae28c0b912
"""

import sqlalchemy as sa
from alembic import op

revision = "4a98c2de6710"
down_revision = "73ae28c0b912"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "orders", sa.Column("payment_method", sa.String(20), nullable=False, server_default="stripe_checkout")
    )
    op.add_column("orders", sa.Column("payment_reference", sa.String(255), nullable=False, server_default=""))
    op.add_column("orders", sa.Column("manual_key", sa.String(36), nullable=True))
    op.create_unique_constraint("uq_orders_manual_key", "orders", ["manual_key"])
    op.alter_column("order_items", "listing_id", existing_type=sa.Integer(), nullable=True)
    op.execute(
        "UPDATE orders SET payment_method = 'stripe_invoice' WHERE id IN "
        "(SELECT order_id FROM bouquet_proposals WHERE order_id IS NOT NULL)"
    )


def downgrade():
    # Custom manual lines cannot be downgraded without deleting financial history.
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM order_items WHERE listing_id IS NULL LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade while custom manual order lines exist")
    op.alter_column("order_items", "listing_id", existing_type=sa.Integer(), nullable=False)
    op.drop_constraint("uq_orders_manual_key", "orders", type_="unique")
    op.drop_column("orders", "manual_key")
    op.drop_column("orders", "payment_reference")
    op.drop_column("orders", "payment_method")
