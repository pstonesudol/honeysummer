"""Track submitted inquiry email attempts and system correspondence.

Revision ID: d64be6148b53
Revises: c8a446f8a28d
"""
from alembic import op
import sqlalchemy as sa

revision = "d64be6148b53"
down_revision = "c8a446f8a28d"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("inquiries", sa.Column("email_delivery", sa.JSON(), nullable=False, server_default="{}"))
    op.alter_column("inquiry_correspondence", "actor_id", nullable=True)


def downgrade():
    # Old schema cannot store system correspondence. Do not downgrade with data.
    op.alter_column("inquiry_correspondence", "actor_id", nullable=False)
    op.drop_column("inquiries", "email_delivery")
