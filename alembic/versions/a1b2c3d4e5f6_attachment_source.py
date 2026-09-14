"""attachment source (merge of extra_document + chat_feedback heads)

Revision ID: a1b2c3d4e5f6
Revises: 09cf9d60fd13, fb0c17ed1234
Create Date: 2026-09-14 14:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = ('09cf9d60fd13', 'fb0c17ed1234')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "attachments",
        sa.Column("source", sa.String(50), nullable=True, server_default="local"),
    )
    op.add_column(
        "attachments",
        sa.Column("source_ref", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("attachments", "source_ref")
    op.drop_column("attachments", "source")
