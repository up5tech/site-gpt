"""v2 extra_documents website index

Revision ID: c9d3e5a71b28
Revises: f7c1d84b2e39
Create Date: 2026-11-16 18:10:00.000000

Two queries filter `extra_documents` on `website_id` and had no index for it:

* the worker's per-website ingest
  (`website_id = X OR (website_id IS NULL AND company_id = Y)`), which read all
  148k rows (7.7 ms) to return 148k-minus-2k, and
* `qa_training.rebuild_qa_document`, which looks one document up by
  `(website_id, name)` and removed 147k rows by filter (4.6 ms).

`(website_id, name)` serves both: the worker only needs the leading column, the QA
lookup uses both. Most documents are company-wide (`website_id IS NULL`), so the
index stays small. Same `CONCURRENTLY` pattern as the other retention indexes: a
failed build leaves an invalid index; drop it with `DROP INDEX CONCURRENTLY` and
re-run.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c9d3e5a71b28'
down_revision: Union[str, Sequence[str], None] = 'f7c1d84b2e39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.get_context().autocommit_block():
        op.create_index(
            'idx_extra_documents_website_id_name',
            'extra_documents',
            ['website_id', 'name'],
            unique=False,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.get_context().autocommit_block():
        op.drop_index(
            'idx_extra_documents_website_id_name',
            table_name='extra_documents',
            postgresql_concurrently=True,
        )
