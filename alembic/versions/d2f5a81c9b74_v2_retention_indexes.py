"""v2 retention indexes

Revision ID: d2f5a81c9b74
Revises: b7d41c9e2f10
Create Date: 2026-11-16 09:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd2f5a81c9b74'
down_revision: Union[str, Sequence[str], None] = 'b7d41c9e2f10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # The retention purge filters every table by `website_id IN (...) AND
    # created_at < cutoff`, and `digest_log` by company + age. Without these each
    # batch was a sequential scan of the whole table.
    op.create_index(
        'idx_chat_messages_website_id_created_at',
        'chat_messages',
        ['website_id', 'created_at'],
        unique=False,
    )
    op.create_index(
        'idx_chat_feedback_website_id_created_at',
        'chat_feedback',
        ['website_id', 'created_at'],
        unique=False,
    )
    op.create_index(
        'idx_handoff_requests_website_id_created_at',
        'handoff_requests',
        ['website_id', 'created_at'],
        unique=False,
    )
    op.create_index(
        'idx_contacts_website_id_created_at',
        'contacts',
        ['website_id', 'created_at'],
        unique=False,
    )
    op.create_index(
        'idx_digest_log_company_id_created_at',
        'digest_log',
        ['company_id', 'created_at'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_digest_log_company_id_created_at', table_name='digest_log')
    op.drop_index('idx_contacts_website_id_created_at', table_name='contacts')
    op.drop_index('idx_handoff_requests_website_id_created_at', table_name='handoff_requests')
    op.drop_index('idx_chat_feedback_website_id_created_at', table_name='chat_feedback')
    op.drop_index('idx_chat_messages_website_id_created_at', table_name='chat_messages')
