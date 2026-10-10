"""Add configurable per-listing delivery fees.

Revision ID: 794b5e7f2a11
Revises: 06df37b3a004
"""

import sqlalchemy as sa
from alembic import op

revision = "794b5e7f2a11"
down_revision = "06df37b3a004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "flower_listings",
        sa.Column("delivery_fee", sa.Numeric(8, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "flower_listings",
        sa.Column("delivery_fee_mode", sa.String(20), nullable=False, server_default="per_listing"),
    )
    op.create_check_constraint("flower_delivery_fee_nonnegative", "flower_listings", "delivery_fee >= 0")
    op.create_check_constraint(
        "flower_delivery_fee_mode_valid",
        "flower_listings",
        "delivery_fee_mode IN ('per_listing', 'per_unit', 'per_order')",
    )


def downgrade() -> None:
    op.drop_constraint("flower_delivery_fee_mode_valid", "flower_listings", type_="check")
    op.drop_constraint("flower_delivery_fee_nonnegative", "flower_listings", type_="check")
    op.drop_column("flower_listings", "delivery_fee_mode")
    op.drop_column("flower_listings", "delivery_fee")
