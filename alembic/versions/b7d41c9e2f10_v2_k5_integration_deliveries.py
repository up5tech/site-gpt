"""v2 k5 integration deliveries

Revision ID: b7d41c9e2f10
Revises: 5fbe6ce28d9b
Create Date: 2026-11-16 07:12:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7d41c9e2f10'
down_revision: Union[str, Sequence[str], None] = '5fbe6ce28d9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Written by hand: autogenerate also re-proposes the timestamptz→DateTime()
    # drift on `api_keys`, `contacts`, `users` and the FK churn on
    # `chat_feedback.website_id`, none of which belongs to this change.
    op.create_table(
        'integration_deliveries',
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('integration_id', sa.Uuid(), nullable=True),
        sa.Column('integration_type', sa.String(length=50), nullable=False),
        sa.Column('integration_name', sa.String(length=255), nullable=False),
        sa.Column('event_id', sa.Uuid(), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('last_status_code', sa.Integer(), nullable=True),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['integration_id'], ['integrations.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('integration_id', 'event_id'),
    )
    op.create_index(
        'idx_integration_deliveries_company_id',
        'integration_deliveries',
        ['company_id'],
        unique=False,
    )
    op.create_index(
        'idx_integration_deliveries_due',
        'integration_deliveries',
        ['status', 'next_attempt_at'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'idx_integration_deliveries_due', table_name='integration_deliveries'
    )
    op.drop_index(
        'idx_integration_deliveries_company_id', table_name='integration_deliveries'
    )
    op.drop_table('integration_deliveries')
