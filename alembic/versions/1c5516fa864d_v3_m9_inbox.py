"""v3 m9 inbox

Revision ID: 1c5516fa864d
Revises: afef1e91e0b5
Create Date: 2026-11-19 09:56:02.070805

M9 adds what a live-agent inbox needs on top of sessions that were only ever a
`session_id` on `chat_messages`: one `conversations` row per session and the
author of an agent message.

Autogenerate proposed the two real changes plus the four known drift changes it
always proposes (naive `DateTime()` ALTERs on `api_keys.last_used_at`/
`revoked_at`, `contacts.consent_at`, `users.reset_token_expires_at`, and the
drop/create of `chat_feedback.website_id`'s FK). Only the inbox changes are real,
so the rest is removed — taking the `ALTER`s would rewrite timezone-aware columns
as naive.

Two details matter operationally:

* `conversations` is new and empty, so its unique `(website_id, session_id)` and
  the queue index `(website_id, state, last_message_at)` are built
  transactionally, like M7/M8. Nothing is backfilled (D2): the row is created
  lazily by `services.conversations` on a session's first message.
* `chat_messages` is a busy table. Adding a nullable column is metadata-only, but
  a foreign key added the normal way validates every existing row under a lock
  that blocks writes. So the constraint is added `NOT VALID` (instant, no scan)
  and then `VALIDATE CONSTRAINT`, which takes only SHARE UPDATE EXCLUSIVE — reads
  and writes keep running while the existing, all-NULL column is checked.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '1c5516fa864d'
down_revision: Union[str, Sequence[str], None] = 'afef1e91e0b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AUTHOR_FK = 'fk_chat_messages_author_user_id'


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'conversations',
        sa.Column('website_id', sa.Uuid(), nullable=False),
        sa.Column('session_id', sa.String(length=255), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('assigned_user_id', sa.Uuid(), nullable=True),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(
            ['assigned_user_id'], ['users.id'], ondelete='SET NULL'
        ),
        sa.ForeignKeyConstraint(['website_id'], ['websites.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('website_id', 'session_id'),
    )
    op.create_index(
        'idx_conversations_website_id_state_last_message_at',
        'conversations',
        ['website_id', 'state', 'last_message_at'],
        unique=False,
    )

    op.add_column(
        'chat_messages', sa.Column('author_user_id', sa.Uuid(), nullable=True)
    )
    op.execute(
        f'ALTER TABLE chat_messages ADD CONSTRAINT {AUTHOR_FK} '
        'FOREIGN KEY (author_user_id) REFERENCES users (id) '
        'ON DELETE SET NULL NOT VALID'
    )
    op.execute(f'ALTER TABLE chat_messages VALIDATE CONSTRAINT {AUTHOR_FK}')


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f'ALTER TABLE chat_messages DROP CONSTRAINT {AUTHOR_FK}')
    op.drop_column('chat_messages', 'author_user_id')
    op.drop_index(
        'idx_conversations_website_id_state_last_message_at',
        table_name='conversations',
    )
    op.drop_table('conversations')
