"""add tenant contact phone and email

Revision ID: 0011_add_tenant_contacts
Revises: 0010_add_marketplace_settings
Create Date: 2026-10-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0011_add_tenant_contacts'
down_revision: Union[str, None] = '0010_add_marketplace_settings'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('platform_settings', sa.Column('contact_phone', sa.String(length=30), nullable=True))
    op.add_column('platform_settings', sa.Column('contact_email', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('platform_settings', 'contact_email')
    op.drop_column('platform_settings', 'contact_phone')