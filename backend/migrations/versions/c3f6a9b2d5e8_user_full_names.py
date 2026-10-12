"""Store full names for all accounts and preserve existing florist contact names."""

import sqlalchemy as sa
from alembic import op

revision = "c3f6a9b2d5e8"
down_revision = "b2e5a8d1c3f4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("full_name", sa.String(200), nullable=False, server_default=""))
    op.execute(
        "UPDATE users SET full_name = COALESCE("
        "(SELECT contact_name FROM florist_profiles WHERE florist_profiles.user_id = users.id), '')"
    )


def downgrade():
    op.drop_column("users", "full_name")
