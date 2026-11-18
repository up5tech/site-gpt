"""v3 m8 topic clusters

Revision ID: afef1e91e0b5
Revises: 76f46b510350
Create Date: 2026-11-18 15:32:05.633385

M8 adds the two tables V3 F2 needs: `topic_clusters` (the named clusters of one
company for one weekly window) and `topic_cluster_runs` (the durable claim that
makes a window run once).

Autogenerate proposed exactly these two tables plus the four known drift changes
it always proposes (naive `DateTime()` ALTERs on `api_keys.last_used_at`/
`revoked_at`, `contacts.consent_at`, `users.reset_token_expires_at`, and the
drop/create of `chat_feedback.website_id`'s FK). Only the new tables are real, so
the rest is removed — taking the `ALTER`s would rewrite timezone-aware columns as
naive and the FK churn would rewrite a constraint to the same definition.

Three constraints carry the feature:

* `topic_cluster_runs` is unique on `(company_id, period_start)`: a duplicate job
  or a second worker loses the insert instead of building the window twice, which
  is what makes the run idempotent.
* `topic_clusters` is unique on `(company_id, period_start, cluster_key)`: a
  rebuild of the same window replaces its clusters by identity rather than
  appending a second copy, and `cluster_key` is derived (not random) so identical
  input yields identical keys.
* `ck_topic_cluster_runs_status` bounds `status` to `running`/`completed`/`failed`,
  so a typo cannot create a run the worker will never pick up or finish.

Indexes: `(status, claimed_at)` is the stale-run recovery scan, and both tables
carry `(company_id, created_at)` for the retention purge and the post-erasure
invalidation. The tables are new and empty, so their indexes are built
transactionally — no traffic to block, and the migration stays atomic (unlike the
`CONCURRENTLY` builds on the busy V2 tables).

`centroid` is `VECTOR(1536)`, the same `EMBEDDING_DIMENSIONS` as `embeddings`:
M8 changes no dimension, so nothing is re-ingested.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR

# revision identifiers, used by Alembic.
revision: str = 'afef1e91e0b5'
down_revision: Union[str, Sequence[str], None] = '76f46b510350'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'topic_cluster_runs',
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error', sa.String(length=500), nullable=True),
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
            "status IN ('running', 'completed', 'failed')",
            name='ck_topic_cluster_runs_status',
        ),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'period_start'),
    )
    op.create_index(
        'idx_topic_cluster_runs_company_id_created_at',
        'topic_cluster_runs',
        ['company_id', 'created_at'],
        unique=False,
    )
    op.create_index(
        'idx_topic_cluster_runs_status_claimed_at',
        'topic_cluster_runs',
        ['status', 'claimed_at'],
        unique=False,
    )
    op.create_table(
        'topic_clusters',
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('cluster_key', sa.String(length=32), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('centroid', VECTOR(dim=1536), nullable=True),
        sa.Column('sampled_messages', sa.Integer(), nullable=False),
        sa.Column('eligible_messages', sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'period_start', 'cluster_key'),
    )
    op.create_index(
        'idx_topic_clusters_company_id_created_at',
        'topic_clusters',
        ['company_id', 'created_at'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'idx_topic_clusters_company_id_created_at', table_name='topic_clusters'
    )
    op.drop_table('topic_clusters')
    op.drop_index(
        'idx_topic_cluster_runs_status_claimed_at', table_name='topic_cluster_runs'
    )
    op.drop_index(
        'idx_topic_cluster_runs_company_id_created_at', table_name='topic_cluster_runs'
    )
    op.drop_table('topic_cluster_runs')
