"""v2 m5 contact consent

Revision ID: 94ca756068a7
Revises: bebd929605ed
Create Date: 2026-11-15 15:04:15.004225

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '94ca756068a7'
down_revision: Union[str, Sequence[str], None] = 'bebd929605ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Autogenerate also proposed naive-DateTime conversions for
    # `api_keys.last_used_at`/`revoked_at` and `users.reset_token_expires_at`,
    # plus a drop/create of `chat_feedback.website_id`'s FK. Both are drift: the
    # timestamptz columns are correct as they are and the FK never changed.
    op.add_column(
        'contacts',
        sa.Column('consent_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('contacts', 'consent_at')
