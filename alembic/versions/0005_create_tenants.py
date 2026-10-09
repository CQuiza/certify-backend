"""create tenants and pivot platform_settings to tenant_id

Revision ID: 0005_create_tenants
Revises: 0004_platform_settings
Create Date: 2026-10-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005_create_tenants'
down_revision: Union[str, None] = '0004_platform_settings'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_SLUG = 'default'


def upgrade() -> None:
    op.create_table('tenants',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('slug', sa.String(length=100), nullable=False),
    sa.Column('domain', sa.String(length=255), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tenants')),
    sa.UniqueConstraint('domain', name=op.f('uq_tenants_domain')),
    sa.UniqueConstraint('slug', name=op.f('uq_tenants_slug'))
    )

    op.execute(
        f"INSERT INTO tenants (name, slug, is_active) "
        f"VALUES ('Certify (predeterminado)', '{_DEFAULT_SLUG}', true)"
    )

    # platform_settings: tenant_key -> tenant_id
    op.add_column('platform_settings', sa.Column('tenant_id', sa.Integer(), nullable=True))
    op.execute(
        "UPDATE platform_settings SET tenant_id = "
        f"(SELECT id FROM tenants WHERE slug='{_DEFAULT_SLUG}' LIMIT 1)"
    )
    op.drop_constraint('uq_platform_settings_tenant_key', 'platform_settings', type_='unique')
    op.drop_column('platform_settings', 'tenant_key')
    op.alter_column('platform_settings', 'tenant_id', existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key(
        op.f('fk_platform_settings_tenant_id_tenants'),
        'platform_settings', 'tenants', ['tenant_id'], ['id'], ondelete='CASCADE',
    )
    op.create_unique_constraint(
        'uq_platform_settings_tenant_id', 'platform_settings', ['tenant_id']
    )


def downgrade() -> None:
    op.drop_constraint('uq_platform_settings_tenant_id', 'platform_settings', type_='unique')
    op.drop_constraint(
        op.f('fk_platform_settings_tenant_id_tenants'), 'platform_settings', type_='foreignkey'
    )
    op.add_column(
        'platform_settings', sa.Column('tenant_key', sa.String(length=100), nullable=True)
    )
    op.execute(f"UPDATE platform_settings SET tenant_key='{_DEFAULT_SLUG}'")
    op.alter_column('platform_settings', 'tenant_key', existing_type=sa.String(length=100), nullable=False)
    op.drop_column('platform_settings', 'tenant_id')
    op.create_unique_constraint('uq_platform_settings_tenant_key', 'platform_settings', ['tenant_key'])
    op.drop_table('tenants')