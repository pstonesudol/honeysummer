"""Reusable gallery image focal points.

Revision ID: 09cb3a8ee77a
Revises: c384f0c736c8
"""

import sqlalchemy as sa
from alembic import op

revision = "09cb3a8ee77a"
down_revision = "c384f0c736c8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("gallery_images", sa.Column("focal_x", sa.Integer(), server_default="50", nullable=False))
    op.add_column("gallery_images", sa.Column("focal_y", sa.Integer(), server_default="50", nullable=False))


def downgrade():
    op.drop_column("gallery_images", "focal_y")
    op.drop_column("gallery_images", "focal_x")
