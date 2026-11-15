"""v2 k4 session tokens

Revision ID: 5fbe6ce28d9b
Revises: 94ca756068a7
Create Date: 2026-11-16 05:57:00.385676

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '5fbe6ce28d9b'
down_revision: Union[str, Sequence[str], None] = '94ca756068a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Autogenerate again proposed the timestamptz→DateTime() conversions for
    # `api_keys.last_used_at`/`revoked_at`, `contacts.consent_at` and
    # `users.reset_token_expires_at`, plus the drop/create of
    # `chat_feedback.website_id`'s FK. All drift; only the new table is real.
    op.create_table(
        'session_tokens',
        sa.Column('website_id', sa.Uuid(), nullable=False),
        sa.Column('session_id', sa.String(length=255), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['website_id'], ['websites.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('website_id', 'session_id'),
    )
    op.create_index(
        'idx_session_tokens_website_id', 'session_tokens', ['website_id'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_session_tokens_website_id', table_name='session_tokens')
    op.drop_table('session_tokens')
