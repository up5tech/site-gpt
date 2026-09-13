"""password reset token

Revision ID: 3f1a9c0d7e22
Revises: 20a8a1bc864f
Create Date: 2026-09-13 08:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '3f1a9c0d7e22'
down_revision: Union[str, Sequence[str], None] = '20a8a1bc864f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('reset_token', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('reset_token_expires_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'reset_token_expires_at')
    op.drop_column('users', 'reset_token')
