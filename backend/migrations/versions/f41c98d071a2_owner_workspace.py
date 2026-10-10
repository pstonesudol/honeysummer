"""Administrative outcomes and idempotent email imports.

Revision ID: f41c98d071a2
Revises: 83e31c55ab49
"""

import sqlalchemy as sa
from alembic import op

revision = "f41c98d071a2"
down_revision = "83e31c55ab49"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "admin_activity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_admin_activity_actor_id", "admin_activity", ["actor_id"])
    op.create_index("ix_admin_activity_created_at", "admin_activity", ["created_at"])
    op.add_column("inquiry_correspondence", sa.Column("source_id", sa.String(255), nullable=True))
    op.create_unique_constraint("uq_correspondence_source_id", "inquiry_correspondence", ["source_id"])


def downgrade():
    op.drop_constraint("uq_correspondence_source_id", "inquiry_correspondence", type_="unique")
    op.drop_column("inquiry_correspondence", "source_id")
    op.drop_table("admin_activity")
