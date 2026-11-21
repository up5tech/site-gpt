"""v4 m10 conversation insights

Revision ID: f33497bc1ecd
Revises: 1c5516fa864d
Create Date: 2026-11-21 06:59:24.643840

M10 adds the derived per-conversation classifications (V4 F2) and fixes the
`attachments.file_type` width the V4-3G gate exposed.

`conversation_insights` holds one row per conversation: the unique
`conversation_id` is the claim lock a run inserts against **and** the erasure
path — the FK cascades, so deleting a conversation deletes its classifications.
The table is new and empty, so its unique constraint and the
`(status, claimed_at)` recovery index are built transactionally, like M7-M9.

`attachments.file_type` was `VARCHAR(50)` while the OOXML MIME types are 73
characters, so a `.pptx` (or `.docx`) upload raised `DataError` on Postgres and
answered 500. Widening the limit is metadata-only in Postgres — no table
rewrite — so the busy `attachments` table is not rewritten; the V4-3G gate's
temporary truncation clamp in `api/upload.py` goes away with it.

Autogenerate proposed the two real changes plus the usual drift: naive
`DateTime()` ALTERs on `api_keys.last_used_at`/`revoked_at`,
`contacts.consent_at`, `users.reset_token_expires_at`, and a drop/create of
`chat_feedback.website_id`'s FK. All of it is removed — taking the `ALTER`s
would rewrite timezone-aware columns as naive.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f33497bc1ecd'
down_revision: Union[str, Sequence[str], None] = '1c5516fa864d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FILE_TYPE_WIDTH = 120
OLD_FILE_TYPE_WIDTH = 50


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'conversation_insights',
        sa.Column('conversation_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('sentiment', sa.String(length=20), nullable=True),
        sa.Column('resolution', sa.String(length=20), nullable=True),
        sa.Column('summary', sa.String(length=280), nullable=True),
        sa.Column('model', sa.String(length=120), nullable=True),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "resolution IS NULL OR resolution IN "
            "('resolved', 'unresolved', 'escalated', 'unknown')",
            name='ck_conversation_insights_resolution',
        ),
        sa.CheckConstraint(
            "sentiment IS NULL OR sentiment IN "
            "('positive', 'neutral', 'negative', 'frustrated')",
            name='ck_conversation_insights_sentiment',
        ),
        sa.CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name='ck_conversation_insights_status',
        ),
        sa.ForeignKeyConstraint(
            ['conversation_id'], ['conversations.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('conversation_id'),
    )
    op.create_index(
        'idx_conversation_insights_status_claimed_at',
        'conversation_insights',
        ['status', 'claimed_at'],
        unique=False,
    )

    op.alter_column(
        'attachments',
        'file_type',
        existing_type=sa.VARCHAR(length=OLD_FILE_TYPE_WIDTH),
        type_=sa.String(length=FILE_TYPE_WIDTH),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema: derived classifications only, plus the file-type clamp.

    Narrowing `file_type` back to 50 would fail on any stored OOXML type, so the
    long values are truncated first — a documented loss of informational
    metadata (the filename extension is what parsing uses).
    """
    op.execute(
        'UPDATE attachments '
        f'SET file_type = left(file_type, {OLD_FILE_TYPE_WIDTH}) '
        f'WHERE length(file_type) > {OLD_FILE_TYPE_WIDTH}'
    )
    op.alter_column(
        'attachments',
        'file_type',
        existing_type=sa.String(length=FILE_TYPE_WIDTH),
        type_=sa.VARCHAR(length=OLD_FILE_TYPE_WIDTH),
        existing_nullable=True,
    )

    op.drop_index(
        'idx_conversation_insights_status_claimed_at',
        table_name='conversation_insights',
    )
    op.drop_table('conversation_insights')
