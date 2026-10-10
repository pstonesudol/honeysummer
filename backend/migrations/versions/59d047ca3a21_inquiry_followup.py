"""Inquiry follow-up workflow.

Revision ID: 59d047ca3a21
Revises: 4a98c2de6710
"""

import sqlalchemy as sa
from alembic import op

revision = "59d047ca3a21"
down_revision = "4a98c2de6710"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("inquiries", sa.Column("stage", sa.String(20), nullable=False, server_default="new"))
    op.add_column("inquiries", sa.Column("follow_up_date", sa.Date(), nullable=True))
    op.add_column("inquiries", sa.Column("internal_notes", sa.Text(), nullable=False, server_default=""))
    op.execute("UPDATE inquiries SET stage = 'closed' WHERE handled = true")
    op.create_index("ix_inquiries_follow_up_date", "inquiries", ["follow_up_date"])
    op.create_check_constraint(
        "inquiry_stage_valid", "inquiries", "stage IN ('new', 'contacted', 'quoted', 'booked', 'closed')"
    )


def downgrade():
    op.drop_constraint("inquiry_stage_valid", "inquiries", type_="check")
    op.drop_index("ix_inquiries_follow_up_date", table_name="inquiries")
    op.drop_column("inquiries", "internal_notes")
    op.drop_column("inquiries", "follow_up_date")
    op.drop_column("inquiries", "stage")
