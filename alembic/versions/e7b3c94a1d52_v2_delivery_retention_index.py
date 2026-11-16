"""v2 delivery retention index

Revision ID: e7b3c94a1d52
Revises: d2f5a81c9b74
Create Date: 2026-11-16 10:20:00.000000

Same reasoning as `d2f5a81c9b74`: `integration_deliveries` is written on every
outbound event, so the index is built `CONCURRENTLY` outside a transaction. A
failed build leaves an invalid index; drop it with `DROP INDEX CONCURRENTLY` and
re-run.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e7b3c94a1d52'
down_revision: Union[str, Sequence[str], None] = 'd2f5a81c9b74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Retention deletes `status IN ('delivered', 'dead') AND created_at < cutoff`
    # and clears `status = 'dead'` payloads; both start from the status.
    with op.get_context().autocommit_block():
        op.create_index(
            'idx_integration_deliveries_status_created_at',
            'integration_deliveries',
            ['status', 'created_at'],
            unique=False,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.get_context().autocommit_block():
        op.drop_index(
            'idx_integration_deliveries_status_created_at',
            table_name='integration_deliveries',
            postgresql_concurrently=True,
        )
