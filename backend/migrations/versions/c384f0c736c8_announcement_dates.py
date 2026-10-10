"""Schedule storefront announcements by Eastern calendar date.

Revision ID: c384f0c736c8
Revises: a7b190e94cf1
"""
from alembic import op
import sqlalchemy as sa

revision = "c384f0c736c8"
down_revision = "a7b190e94cf1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("announcements", sa.Column("starts_on", sa.Date(), nullable=True))
    op.add_column("announcements", sa.Column("ends_on", sa.Date(), nullable=True))


def downgrade():
    op.drop_column("announcements", "ends_on")
    op.drop_column("announcements", "starts_on")
