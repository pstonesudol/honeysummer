"""Inventory journal, hold deadlines, and Stripe event reconciliation.

Revision ID: 8c55d1b6a940
Revises: 794b5e7f2a11
"""

from alembic import op
import sqlalchemy as sa


revision = "8c55d1b6a940"
down_revision = "794b5e7f2a11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "flower_available_nonnegative", "flower_listings", "quantity_available >= 0"
    )
    op.add_column("orders", sa.Column("hold_expires_at", sa.DateTime(timezone=True)))
    op.add_column("orders", sa.Column("fulfilled_at", sa.DateTime(timezone=True)))
    op.add_column("orders", sa.Column("restocked_at", sa.DateTime(timezone=True)))
    op.add_column("orders", sa.Column("stripe_payment_intent_id", sa.String(255)))
    op.create_index("ix_orders_stripe_payment_intent_id", "orders", ["stripe_payment_intent_id"])
    op.create_table(
        "inventory_movements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("listing_id", sa.Integer(), sa.ForeignKey("flower_listings.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id")),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("units > 0 OR kind = 'opening'", name="movement_units_positive"),
    )
    op.create_index("ix_inventory_movements_listing_id", "inventory_movements", ["listing_id"])
    op.create_index("ix_inventory_movements_order_id", "inventory_movements", ["order_id"])
    op.execute(
        """INSERT INTO inventory_movements
           (listing_id, kind, delta, units, reason, source, created_at)
           SELECT id, 'opening', quantity_available, quantity_available,
                  'Balance at inventory ledger migration', 'migration', CURRENT_TIMESTAMP
           FROM flower_listings"""
    )
    op.execute(
        """INSERT INTO inventory_movements
           (listing_id, order_id, kind, delta, units, reason, source, created_at)
           SELECT oi.listing_id, oi.order_id, 'legacy_hold', 0, oi.quantity,
                  'Reservation predates stock journal', 'migration', CURRENT_TIMESTAMP
           FROM order_items oi JOIN orders o ON o.id = oi.order_id
           WHERE o.status = 'pending'"""
    )
    op.create_table(
        "stripe_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(255), nullable=False, unique=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id")),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("outcome", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "order_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("recipient", sa.String(10), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("order_id", "recipient", name="uq_order_notification_recipient"),
    )
    op.create_index("ix_order_notifications_order_id", "order_notifications", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_order_notifications_order_id", "order_notifications")
    op.drop_table("order_notifications")
    op.drop_table("stripe_events")
    op.drop_index("ix_inventory_movements_order_id", "inventory_movements")
    op.drop_index("ix_inventory_movements_listing_id", "inventory_movements")
    op.drop_table("inventory_movements")
    op.drop_index("ix_orders_stripe_payment_intent_id", "orders")
    op.drop_column("orders", "stripe_payment_intent_id")
    op.drop_column("orders", "fulfilled_at")
    op.drop_column("orders", "restocked_at")
    op.drop_column("orders", "hold_expires_at")
    op.drop_constraint("flower_available_nonnegative", "flower_listings", type_="check")
