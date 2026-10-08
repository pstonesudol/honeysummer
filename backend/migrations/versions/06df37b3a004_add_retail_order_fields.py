"""add retail order fields

Revision ID: 06df37b3a004
Revises: 10e832624a08
Create Date: 2026-10-07 20:01:56.787824

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '06df37b3a004'
down_revision: Union[str, None] = '10e832624a08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("orders", "customer_id", existing_type=sa.Integer(), nullable=True)
    op.add_column(
        "orders",
        sa.Column(
            "customer_name", sa.String(length=200), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "customer_email", sa.String(length=254), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "customer_phone", sa.String(length=40), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "channel",
            sa.String(length=10),
            nullable=False,
            server_default="wholesale",
        ),
    )
    op.add_column(
        "orders", sa.Column("notes", sa.Text(), nullable=False, server_default="")
    )


def downgrade() -> None:
    op.drop_column("orders", "notes")
    op.drop_column("orders", "channel")
    op.drop_column("orders", "customer_phone")
    op.drop_column("orders", "customer_email")
    op.drop_column("orders", "customer_name")
    op.alter_column("orders", "customer_id", existing_type=sa.Integer(), nullable=False)
