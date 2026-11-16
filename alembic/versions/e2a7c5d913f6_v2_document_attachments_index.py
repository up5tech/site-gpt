"""v2 document expiry anti-join index

Revision ID: e2a7c5d913f6
Revises: d5b9c4e2a87f
Create Date: 2026-11-16 16:20:00.000000

`document_expiry` asks, once per candidate document, "does this document hold an
upload from inside the window?" (`attachments.extra_document_id = ... AND
attachments.created_at >= cutoff`). With only `idx_attachments_extra_document_id`,
each probe walks that document's attachments in the heap to read `created_at`, so
when most expired documents were re-used recently the anti-join does a heap fetch per
attachment row (measured: 5,116 probes, 24,664 buffers).

The composite answers the question from the index alone. Same `CONCURRENTLY` pattern
as the other retention indexes: a failed build leaves an invalid index; drop it with
`DROP INDEX CONCURRENTLY` and re-run.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e2a7c5d913f6'
down_revision: Union[str, Sequence[str], None] = 'd5b9c4e2a87f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.get_context().autocommit_block():
        op.create_index(
            'idx_attachments_extra_document_id_created_at',
            'attachments',
            ['extra_document_id', 'created_at'],
            unique=False,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.get_context().autocommit_block():
        op.drop_index(
            'idx_attachments_extra_document_id_created_at',
            table_name='attachments',
            postgresql_concurrently=True,
        )
