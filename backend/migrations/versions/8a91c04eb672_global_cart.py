"""Persistent checkout attempts for separate storefront carts."""

import sqlalchemy as sa
from alembic import op

revision = "8a91c04eb672"
down_revision = "f41c98d071a2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("orders", sa.Column("checkout_key", sa.String(36), nullable=True))
    op.add_column("orders", sa.Column("checkout_url", sa.Text(), server_default="", nullable=False))
    op.create_index("ix_orders_checkout_key", "orders", ["checkout_key"], unique=True)


def downgrade():
    op.drop_index("ix_orders_checkout_key", table_name="orders")
    op.drop_column("orders", "checkout_url")
    op.drop_column("orders", "checkout_key")
