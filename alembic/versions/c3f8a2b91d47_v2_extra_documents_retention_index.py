"""v2 document retention index

Revision ID: c3f8a2b91d47
Revises: a4c1e9d7f320
Create Date: 2026-11-16 14:10:00.000000

The document pass walks

    extra_documents WHERE company_id = ... AND created_at < cutoff
    ORDER BY created_at LIMIT 1000

and `idx_extra_documents_company_id` only covers the first column, so a tenant
holding most of the table forced a full scan of its rows to find the expired tail
(measured: 198k rows read for 1000 returned). The composite index covers the tenant
lookup and the range/ordering together. Same `CONCURRENTLY` pattern as
`d2f5a81c9b74`/`e7b3c94a1d52`/`a4c1e9d7f320`: a failed build leaves an invalid
index; drop it with `DROP INDEX CONCURRENTLY` and re-run.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3f8a2b91d47'
down_revision: Union[str, Sequence[str], None] = 'a4c1e9d7f320'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.get_context().autocommit_block():
        op.create_index(
            'idx_extra_documents_company_id_created_at',
            'extra_documents',
            ['company_id', 'created_at'],
            unique=False,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.get_context().autocommit_block():
        op.drop_index(
            'idx_extra_documents_company_id_created_at',
            table_name='extra_documents',
            postgresql_concurrently=True,
        )
