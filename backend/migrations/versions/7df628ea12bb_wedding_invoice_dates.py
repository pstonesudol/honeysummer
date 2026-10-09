"""Owner-selected send mode and dated wedding invoice schedule.

Revision ID: 7df628ea12bb
Revises: 6bca409fb100
"""
from alembic import op
import sqlalchemy as sa

revision = "7df628ea12bb"
down_revision = "6bca409fb100"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("wedding_quotes", sa.Column("initial_send_mode", sa.String(12), nullable=False, server_default="manual"))
    op.add_column("wedding_quotes", sa.Column("initial_send_date", sa.Date(), nullable=True))
    op.add_column("wedding_quotes", sa.Column("initial_due_date", sa.Date(), nullable=True))
    op.add_column("wedding_quotes", sa.Column("balance_send_mode", sa.String(12), nullable=False, server_default="manual"))
    op.add_column("wedding_quotes", sa.Column("balance_send_date", sa.Date(), nullable=True))
    op.add_column("wedding_quotes", sa.Column("balance_due_date", sa.Date(), nullable=True))


def downgrade():
    for column in ("balance_due_date", "balance_send_date", "balance_send_mode", "initial_due_date", "initial_send_date", "initial_send_mode"):
        op.drop_column("wedding_quotes", column)
