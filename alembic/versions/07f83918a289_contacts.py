"""contacts

Revision ID: 07f83918a289
Revises: a1b2c3d4e5f6
Create Date: 2026-09-17 09:25:27.121859

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '07f83918a289'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('contacts',
    sa.Column('website_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.String(length=255), nullable=False),
    sa.Column('first_name', sa.String(length=255), nullable=False),
    sa.Column('last_name', sa.String(length=255), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['website_id'], ['websites.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('website_id', 'session_id')
    )
    op.create_index('idx_contacts_website_id', 'contacts', ['website_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_contacts_website_id', table_name='contacts')
    op.drop_table('contacts')
