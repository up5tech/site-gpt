"""chat feedback

Revision ID: fb0c17ed1234
Revises: 3f1a9c0d7e22
Create Date: 2026-09-13 16:15:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "fb0c17ed1234"
down_revision: Union[str, Sequence[str], None] = "3f1a9c0d7e22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "chat_feedback",
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("rating", sa.String(length=20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["websites.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_chat_feedback_website_id", "chat_feedback", ["website_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_chat_feedback_website_id", table_name="chat_feedback")
    op.drop_table("chat_feedback")
