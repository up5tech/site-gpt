"""v6 m13 tenant audit logs

V6-14's tenant-admin trail (D13 reopened 2026-11-27): one append-only row per
security-relevant tenant action — actor, company, action, target, time and an
already-redacted JSON detail. No payload, credential or transcript column exists.

Two indexes: `(company_id, created_at)` for the company-scoped newest-first read
and `created_at` alone for the one-year retention purge. Both FKs behave like the
rest of the schema — the company cascades (deleting it removes its trail) and the
actor is `SET NULL` (the row keeps `actor_label`, so the trail outlives an
account).

Revision ID: c1f4a7d29b30
Revises: 0b22b30bf930
Create Date: 2026-11-27 09:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c1f4a7d29b30"
down_revision: Union[str, Sequence[str], None] = "0b22b30bf930"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "tenant_audit_logs",
        sa.Column("company_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_tenant_audit_logs_company_created",
        "tenant_audit_logs",
        ["company_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_tenant_audit_logs_created_at",
        "tenant_audit_logs",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "idx_tenant_audit_logs_created_at", table_name="tenant_audit_logs"
    )
    op.drop_index(
        "idx_tenant_audit_logs_company_created", table_name="tenant_audit_logs"
    )
    op.drop_table("tenant_audit_logs")
