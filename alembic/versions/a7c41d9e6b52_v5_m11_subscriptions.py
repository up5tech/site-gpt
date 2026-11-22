"""v5 m11 subscriptions

Revision ID: a7c41d9e6b52
Revises: f33497bc1ecd
Create Date: 2026-11-22 09:30:00.000000

M11 adds the V5 F2 billing state: one `subscriptions` row per company and one
minimal `billing_events` receipt per Stripe event id.

`subscriptions.company_id` is unique, so a second Checkout retry cannot create a
second paid subscription for one company; `stripe_customer_id` and
`stripe_subscription_id` are unique too, so a webhook's provider id maps to
exactly one tenant. `last_event_at` is the out-of-order guard and the
`(status, current_period_end)` index is what the V5 platform console will list
renewals by.

`billing_events.stripe_event_id` is the replay lock: the row is inserted before
any state change, so a duplicate delivery loses the insert instead of applying
twice. Only the id, type and Stripe creation time are kept — no raw payload, no
card data.

Both tables are new and empty, so their unique constraints and indexes build
transactionally (no `CONCURRENTLY`, no autocommit block), like M7-M10. An empty
database gets them from the start; the downgrade removes both tables, discarding
billing state, which is why it is only safe on a disposable database.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a7c41d9e6b52'
down_revision: Union[str, Sequence[str], None] = 'f33497bc1ecd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'subscriptions',
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('plan_code', sa.String(length=64), nullable=False),
        sa.Column('interval', sa.String(length=16), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('stripe_customer_id', sa.String(length=255), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(length=255), nullable=True),
        sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False),
        sa.Column('canceled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_event_at', sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('incomplete', 'trialing', 'active', 'past_due', "
            "'unpaid', 'canceled', 'paused')",
            name='ck_subscriptions_status',
        ),
        sa.CheckConstraint(
            "interval IS NULL OR interval IN ('month', 'year')",
            name='ck_subscriptions_interval',
        ),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id'),
        sa.UniqueConstraint('stripe_customer_id'),
        sa.UniqueConstraint('stripe_subscription_id'),
    )
    op.create_index(
        'idx_subscriptions_status_current_period_end',
        'subscriptions',
        ['status', 'current_period_end'],
        unique=False,
    )

    op.create_table(
        'billing_events',
        sa.Column('stripe_event_id', sa.String(length=255), nullable=False),
        sa.Column('type', sa.String(length=100), nullable=False),
        sa.Column('stripe_created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stripe_event_id'),
    )
    op.create_index(
        'idx_billing_events_created_at',
        'billing_events',
        ['created_at'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema: billing state and its receipts are discarded."""
    op.drop_index('idx_billing_events_created_at', table_name='billing_events')
    op.drop_table('billing_events')
    op.drop_index(
        'idx_subscriptions_status_current_period_end', table_name='subscriptions'
    )
    op.drop_table('subscriptions')
