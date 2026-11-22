"""v5 m12 platform owner and audit

Operator access for V5 Wave 4 (V5-40/D10): one row per grant in
`platform_owners`, revoked by timestamp so history survives, with a partial
unique index keeping at most one **active** grant per user — the same pattern as
`embed_tokens`, which is why it is spelled out here rather than left to a plain
unique constraint. `platform_audit_logs` is the append-only trail: actor, action,
target, time and an already-redacted JSON detail, with no payload/credential
column.

Wave 4 extends the same still-unapplied revision (V5-42/V5-43): `catalog_plans`
and `plan_prices` carry the durable operator-managed catalog, and
`platform_settings` stores only the typed, non-secret allowlist overrides. Price
rows are immutable and one per plan is active (partial unique index), which is
what a checkout resolves against.

All five tables are new, so their indexes are built transactionally (no
`CONCURRENTLY`), and this stays the sole head chained from M11.

Revision ID: 0b22b30bf930
Revises: a7c41d9e6b52
Create Date: 2026-11-22 12:32:53.557780
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0b22b30bf930"
down_revision: Union[str, Sequence[str], None] = "a7c41d9e6b52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "platform_audit_logs",
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_label", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_platform_audit_logs_created_at",
        "platform_audit_logs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "idx_platform_audit_logs_target",
        "platform_audit_logs",
        ["target_type", "target_id"],
        unique=False,
    )
    op.create_table(
        "platform_owners",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_platform_owners_revoked_at",
        "platform_owners",
        ["revoked_at"],
        unique=False,
    )
    # The invariant: one active grant per user. A plain unique index on user_id
    # would reject re-granting after a revoke and destroy the history.
    op.create_index(
        "uq_platform_owners_user_id_active",
        "platform_owners",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
        sqlite_where=sa.text("revoked_at IS NULL"),
    )
    op.create_table(
        "catalog_plans",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("limits", sa.JSON(), nullable=False),
        sa.Column("self_serve_checkout", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_catalog_plans_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(
        "idx_catalog_plans_status", "catalog_plans", ["status"], unique=False
    )
    op.create_table(
        "plan_prices",
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("interval", sa.String(length=16), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("price_minor", sa.Integer(), nullable=False),
        sa.Column("stripe_price_id", sa.String(length=255), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "interval IN ('month', 'year')", name="ck_plan_prices_interval"
        ),
        sa.CheckConstraint(
            "price_minor >= 0", name="ck_plan_prices_price_minor"
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["catalog_plans.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stripe_price_id"),
    )
    op.create_index(
        "idx_plan_prices_plan_id", "plan_prices", ["plan_id"], unique=False
    )
    # One active price per plan; archived rows remain as price history.
    op.create_index(
        "uq_plan_prices_active_plan",
        "plan_prices",
        ["plan_id"],
        unique=True,
        postgresql_where=sa.text("active"),
        sqlite_where=sa.text("active"),
    )
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )


def downgrade() -> None:
    """Downgrade schema.

    Drops the operator grants and the audit trail with the tables. An operator
    grant is disposable deployment state, but losing the audit rows is not
    recoverable, so export them first if a downgrade is ever required.
    """
    op.drop_table("platform_settings")
    op.drop_index("uq_plan_prices_active_plan", table_name="plan_prices")
    op.drop_index("idx_plan_prices_plan_id", table_name="plan_prices")
    op.drop_table("plan_prices")
    op.drop_index("idx_catalog_plans_status", table_name="catalog_plans")
    op.drop_table("catalog_plans")
    op.drop_index(
        "uq_platform_owners_user_id_active",
        table_name="platform_owners",
        postgresql_where=sa.text("revoked_at IS NULL"),
        sqlite_where=sa.text("revoked_at IS NULL"),
    )
    op.drop_index("idx_platform_owners_revoked_at", table_name="platform_owners")
    op.drop_table("platform_owners")
    op.drop_index(
        "idx_platform_audit_logs_target", table_name="platform_audit_logs"
    )
    op.drop_index(
        "idx_platform_audit_logs_created_at", table_name="platform_audit_logs"
    )
    op.drop_table("platform_audit_logs")
