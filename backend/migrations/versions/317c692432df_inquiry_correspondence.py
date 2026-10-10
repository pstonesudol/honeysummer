"""Manual customer correspondence history.

Revision ID: 317c692432df
Revises: 09cb3a8ee77a
"""
from alembic import op
import sqlalchemy as sa

revision = "317c692432df"
down_revision = "09cb3a8ee77a"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("inquiry_correspondence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inquiry_id", sa.Integer(), sa.ForeignKey("inquiries.id"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("direction", sa.String(length=12), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("direction IN ('received', 'sent')", name="correspondence_direction_valid"),
    )
    op.create_index("ix_inquiry_correspondence_inquiry_id", "inquiry_correspondence", ["inquiry_id"])


def downgrade():
    op.drop_index("ix_inquiry_correspondence_inquiry_id", table_name="inquiry_correspondence")
    op.drop_table("inquiry_correspondence")
