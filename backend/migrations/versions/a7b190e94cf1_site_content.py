"""Persist owner-editable storefront copy.

Revision ID: a7b190e94cf1
Revises: 751e841829ae
"""

import sqlalchemy as sa
from alembic import op

revision = "a7b190e94cf1"
down_revision = "751e841829ae"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "site_content",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("site_content")
