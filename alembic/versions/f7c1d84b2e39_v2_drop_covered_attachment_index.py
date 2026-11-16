"""v2 drop the covered attachment index

Revision ID: f7c1d84b2e39
Revises: e2a7c5d913f6
Create Date: 2026-11-16 17:15:00.000000

`idx_attachments_extra_document_id_created_at` leads with `extra_document_id`, so
every lookup the old single-column `idx_attachments_extra_document_id` served can use
the composite. Keeping both pays a second index's write cost on every upload.

Dropped `CONCURRENTLY` for the same reason the retention indexes are built that way:
a plain `DROP INDEX` takes an ACCESS EXCLUSIVE lock and blocks reads and writes on
`attachments`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f7c1d84b2e39'
down_revision: Union[str, Sequence[str], None] = 'e2a7c5d913f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.get_context().autocommit_block():
        op.drop_index(
            'idx_attachments_extra_document_id',
            table_name='attachments',
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.get_context().autocommit_block():
        op.create_index(
            'idx_attachments_extra_document_id',
            'attachments',
            ['extra_document_id'],
            unique=False,
            postgresql_concurrently=True,
        )
