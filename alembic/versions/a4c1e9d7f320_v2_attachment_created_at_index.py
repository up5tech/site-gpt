"""v2 attachment retention index

Revision ID: a4c1e9d7f320
Revises: e7b3c94a1d52
Create Date: 2026-11-16 13:05:00.000000

The retention purge walks expired uploads with

    attachments a LEFT JOIN extra_documents ed ... LEFT JOIN users u ...
    WHERE a.created_at < cutoff AND (ed.company_id = ... OR u.company_id = ...)
    ORDER BY a.created_at LIMIT 1000

and `attachments` had no index on `created_at`, so every batch sorted (or scanned)
the whole upload table. Same reasoning as `d2f5a81c9b74`/`e7b3c94a1d52`:
`attachments` is written on every upload, so the index is built `CONCURRENTLY`
outside a transaction. A failed build leaves an invalid index; drop it with
`DROP INDEX CONCURRENTLY` and re-run.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a4c1e9d7f320'
down_revision: Union[str, Sequence[str], None] = 'e7b3c94a1d52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # The filter and the ORDER BY of the retention batch select are both on
    # `created_at`, so one btree serves the range scan and the ordering.
    with op.get_context().autocommit_block():
        op.create_index(
            'idx_attachments_created_at',
            'attachments',
            ['created_at'],
            unique=False,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.get_context().autocommit_block():
        op.drop_index(
            'idx_attachments_created_at',
            table_name='attachments',
            postgresql_concurrently=True,
        )
