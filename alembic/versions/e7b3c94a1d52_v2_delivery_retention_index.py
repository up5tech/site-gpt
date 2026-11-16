"""v2 delivery retention index

Revision ID: e7b3c94a1d52
Revises: d2f5a81c9b74
Create Date: 2026-11-16 10:20:00.000000

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
    op.create_index(
        'idx_integration_deliveries_status_created_at',
        'integration_deliveries',
        ['status', 'created_at'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'idx_integration_deliveries_status_created_at',
        table_name='integration_deliveries',
    )
