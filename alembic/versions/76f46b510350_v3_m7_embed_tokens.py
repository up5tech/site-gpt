"""v3 m7 embed tokens

Revision ID: 76f46b510350
Revises: c9d3e5a71b28
Create Date: 2026-11-18 14:14:19.049930

M7 adds `embed_tokens`, the per-website token a deployed widget snippet can
carry (V3 F4). Autogenerate proposed exactly this table plus the four known
drift changes it always proposes (naive `DateTime()` ALTERs on
`api_keys.last_used_at`/`revoked_at`, `contacts.consent_at`,
`users.reset_token_expires_at`, and the drop/create of
`chat_feedback.website_id`'s FK); only the new table is real, so the rest is
removed.

Two constraints carry the feature:

* `token_hash` is unique across the table — one hash can never identify two
  rows.
* `uq_embed_tokens_website_id_active` is a **partial** unique index on
  `website_id WHERE revoked_at IS NULL`: a website has at most one active token,
  while revoked rows accumulate as history. Rotation therefore has to revoke the
  old row and insert the replacement inside one transaction; a second insert
  while the old row is still active fails in the database, not in the service.

`embed_tokens` is brand new and empty, so its indexes are built transactionally
(unlike the `CONCURRENTLY` builds on the busy V2 tables): there is no traffic to
block, and a plain build keeps the migration atomic.

No `embeddings`/`EMBEDDING_DIMENSIONS` change: M7 needs no re-ingest.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '76f46b510350'
down_revision: Union[str, Sequence[str], None] = 'c9d3e5a71b28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'embed_tokens',
        sa.Column('website_id', sa.Uuid(), nullable=False),
        sa.Column('token_prefix', sa.String(length=12), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index(
        'uq_embed_tokens_website_id_active',
        'embed_tokens',
        ['website_id'],
        unique=True,
        postgresql_where=sa.text('revoked_at IS NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drops the token rows themselves: a website that had tokens in `enforce`
    # mode is back to tokenless requests, which `compat` accepts. Roll the app
    # code back before downgrading so no deployed snippet still sends one.
    op.drop_index(
        'uq_embed_tokens_website_id_active', table_name='embed_tokens'
    )
    op.drop_table('embed_tokens')
