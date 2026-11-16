"""v2 retention indexes

Revision ID: d2f5a81c9b74
Revises: b7d41c9e2f10
Create Date: 2026-11-16 09:05:00.000000

These are built with `CREATE INDEX CONCURRENTLY`: a plain `CREATE INDEX` takes a
SHARE lock that blocks every write to the table for as long as the build runs, and
`chat_messages` is the busiest table in the schema. `CONCURRENTLY` cannot run
inside a transaction, so each statement gets Alembic's `autocommit_block()`.

Caveat: a concurrent build that fails leaves an **invalid** index behind (it is
ignored by the planner but still maintained). If a run is interrupted, drop the
index (`DROP INDEX CONCURRENTLY ...`) and run the migration again; the script
itself is not idempotent.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd2f5a81c9b74'
down_revision: Union[str, Sequence[str], None] = 'b7d41c9e2f10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The retention purge filters every table by `website_id IN (...) AND
# created_at < cutoff`, and `digest_log` by company + age. Without these each
# batch was a sequential scan of the whole table.
INDEXES: tuple[tuple[str, str, list[str]], ...] = (
    ('idx_chat_messages_website_id_created_at', 'chat_messages', ['website_id', 'created_at']),
    ('idx_chat_feedback_website_id_created_at', 'chat_feedback', ['website_id', 'created_at']),
    (
        'idx_handoff_requests_website_id_created_at',
        'handoff_requests',
        ['website_id', 'created_at'],
    ),
    ('idx_contacts_website_id_created_at', 'contacts', ['website_id', 'created_at']),
    ('idx_digest_log_company_id_created_at', 'digest_log', ['company_id', 'created_at']),
)


def upgrade() -> None:
    """Upgrade schema."""
    for name, table, columns in INDEXES:
        # One autocommit block per index: each build commits on its own, and a
        # failure on the fourth does not roll back the first three.
        with op.get_context().autocommit_block():
            op.create_index(
                name,
                table,
                columns,
                unique=False,
                postgresql_concurrently=True,
            )


def downgrade() -> None:
    """Downgrade schema."""
    for name, table, _columns in reversed(INDEXES):
        # `DROP INDEX CONCURRENTLY` cannot run in a transaction either.
        with op.get_context().autocommit_block():
            op.drop_index(
                name,
                table_name=table,
                postgresql_concurrently=True,
            )
