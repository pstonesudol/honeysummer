"""Rename the owner role to admin.

Revision ID: a1d4f7c9b2e3
Revises: e6f3f90ba613
"""

from alembic import op

revision = "a1d4f7c9b2e3"
down_revision = "e6f3f90ba613"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'owner'")


def downgrade():
    op.execute("UPDATE users SET role = 'owner' WHERE role = 'admin'")
