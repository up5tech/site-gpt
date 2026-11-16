"""v2 drop the covered document index

Revision ID: d5b9c4e2a87f
Revises: c3f8a2b91d47
Create Date: 2026-11-16 15:05:00.000000

`idx_extra_documents_company_id_created_at` has `company_id` as its leading column,
so every lookup the old single-column `idx_extra_documents_company_id` served can use
the composite instead. Keeping both only pays the second index's write cost on every
document insert/delete/update.

Dropped `CONCURRENTLY` for the same reason the retention indexes are built that way:
a plain `DROP INDEX` takes an ACCESS EXCLUSIVE lock and blocks reads and writes on
`extra_documents` for the duration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd5b9c4e2a87f'
down_revision: Union[str, Sequence[str], None] = 'c3f8a2b91d47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.get_context().autocommit_block():
        op.drop_index(
            'idx_extra_documents_company_id',
            table_name='extra_documents',
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.get_context().autocommit_block():
        op.create_index(
            'idx_extra_documents_company_id',
            'extra_documents',
            ['company_id'],
            unique=False,
            postgresql_concurrently=True,
        )
