"""add marketplace payment settings per tenant

Revision ID: 0010_add_marketplace_settings
Revises: 0009_add_order_tenant
Create Date: 2026-10-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0010_add_marketplace_settings'
down_revision: Union[str, None] = '0009_add_order_tenant'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('platform_settings', sa.Column('mercadopago_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('platform_settings', sa.Column('mercadopago_marketplace_user_id', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('platform_settings', 'mercadopago_marketplace_user_id')
    op.drop_column('platform_settings', 'mercadopago_enabled')