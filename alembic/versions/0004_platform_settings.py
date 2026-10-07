"""create platform_settings and email_templates

Revision ID: 0004_platform_settings
Revises: 0003_create_system_logs
Create Date: 2026-10-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004_platform_settings'
down_revision: Union[str, None] = '0003_create_system_logs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('platform_settings',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('tenant_key', sa.String(length=100), nullable=False),
    sa.Column('organization_name', sa.String(length=255), nullable=True),
    sa.Column('dashboard_message', sa.Text(), nullable=True),
    sa.Column('branding_logo_object_key', sa.String(length=255), nullable=True),
    sa.Column('smtp_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('smtp_host', sa.String(length=255), nullable=True),
    sa.Column('smtp_port', sa.Integer(), nullable=True),
    sa.Column('smtp_user', sa.String(length=255), nullable=True),
    sa.Column('smtp_password_encrypted', sa.Text(), nullable=True),
    sa.Column('smtp_tls', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('email_from', sa.String(length=255), nullable=True),
    sa.Column('email_from_name', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name=op.f('fk_platform_settings_updated_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_platform_settings')),
    sa.UniqueConstraint('tenant_key', name=op.f('uq_platform_settings_tenant_key'))
    )
    op.create_table('email_templates',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('platform_settings_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=50), nullable=False),
    sa.Column('subject', sa.String(length=255), nullable=False),
    sa.Column('body_html', sa.Text(), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.Integer(), nullable=True),
    sa.CheckConstraint("kind IN ('credentials', 'certificate_issued', 'certificate_expired')", name=op.f('ck_email_templates_kind')),
    sa.ForeignKeyConstraint(['platform_settings_id'], ['platform_settings.id'], name=op.f('fk_email_templates_platform_settings_id_platform_settings'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name=op.f('fk_email_templates_updated_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_email_templates')),
    sa.UniqueConstraint('platform_settings_id', 'kind', name=op.f('uq_email_template_settings_kind'))
    )


def downgrade() -> None:
    op.drop_table('email_templates')
    op.drop_table('platform_settings')