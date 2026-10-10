"""Store wholesale account request details on the florist profile.

Revision ID: 16ab07d4e561
Revises: 8c55d1b6a940
"""

import sqlalchemy as sa
from alembic import op

revision = "16ab07d4e561"
down_revision = "8c55d1b6a940"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("florist_profiles", sa.Column("contact_name", sa.String(200), nullable=False, server_default=""))
    op.add_column("florist_profiles", sa.Column("business_type", sa.String(30), nullable=False, server_default=""))
    op.add_column("florist_profiles", sa.Column("website", sa.String(500), nullable=False, server_default=""))
    op.add_column("florist_profiles", sa.Column("about_work", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("florist_profiles", "about_work")
    op.drop_column("florist_profiles", "website")
    op.drop_column("florist_profiles", "business_type")
    op.drop_column("florist_profiles", "contact_name")
