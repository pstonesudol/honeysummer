"""Keep void wedding invoices while allowing a new payment attempt.

Revision ID: 7e18b051c429
Revises: 59bad80e7446
"""
from alembic import op
import sqlalchemy as sa

revision = "7e18b051c429"
down_revision = "59bad80e7446"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("wedding_invoices", sa.Column("revision", sa.Integer(), server_default="1", nullable=False))
    op.drop_constraint("uq_wedding_invoice_step", "wedding_invoices", type_="unique")
    op.create_unique_constraint("uq_wedding_invoice_revision", "wedding_invoices", ["quote_id", "step", "revision"])


def downgrade():
    # Revisions cannot be compressed into the old uniqueness constraint without
    # losing audit history. Do not downgrade after a revised invoice has been sent.
    op.drop_constraint("uq_wedding_invoice_revision", "wedding_invoices", type_="unique")
    op.create_unique_constraint("uq_wedding_invoice_step", "wedding_invoices", ["quote_id", "step"])
    op.drop_column("wedding_invoices", "revision")
