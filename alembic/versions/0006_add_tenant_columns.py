"""add tenant_id to tenant-scoped tables (backfill to default)

Revision ID: 0006_add_tenant_columns
Revises: 0005_create_tenants
Create Date: 2026-10-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006_add_tenant_columns'
down_revision: Union[str, None] = '0005_create_tenants'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_SLUG = 'default'

_SCAPED_TABLES = [
    "users",
    "courses",
    "certificate_types",
    "modules",
    "lessons",
    "lesson_files",
    "lesson_tasks",
    "task_submissions",
    "module_assessments",
    "assessment_questions",
    "assessment_options",
    "user_assessment_attempts",
    "user_assessment_answers",
    "user_progress",
    "course_enrollments",
    "certificates",
    "pending_certificates",
    "certificate_audit",
    "email_audit",
    "user_audit",
]


def _default_tenant_sql() -> str:
    return f"(SELECT id FROM tenants WHERE slug='{_DEFAULT_SLUG}' LIMIT 1)"


def upgrade() -> None:
    for table in _SCAPED_TABLES:
        op.add_column(table, sa.Column('tenant_id', sa.Integer(), nullable=True))
        op.execute(f"UPDATE {table} SET tenant_id = {_default_tenant_sql()}")
        op.alter_column(table, 'tenant_id', existing_type=sa.Integer(), nullable=False)
        op.create_foreign_key(
            op.f(f'fk_{table}_tenant_id_tenants'),
            table, 'tenants', ['tenant_id'], ['id'], ondelete='CASCADE',
        )
        op.create_index(op.f(f'ix_{table}_tenant_id'), table, ['tenant_id'], unique=False)

    # system_logs: nullable (logs globales pueden carecer de tenant)
    op.add_column('system_logs', sa.Column('tenant_id', sa.Integer(), nullable=True))
    op.execute(f"UPDATE system_logs SET tenant_id = {_default_tenant_sql()}")
    op.create_foreign_key(
        op.f('fk_system_logs_tenant_id_tenants'),
        'system_logs', 'tenants', ['tenant_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index(op.f('ix_system_logs_tenant_id'), 'system_logs', ['tenant_id'], unique=False)

    # users: unicidad por-tenant (email / identidad / teléfono)
    op.drop_constraint('users_email_key', 'users', type_='unique')
    op.drop_constraint('users_identity_number_key', 'users', type_='unique')
    op.drop_constraint('users_phone_number_key', 'users', type_='unique')
    op.create_unique_constraint('users_tenant_email_key', 'users', ['tenant_id', 'email'])
    op.create_unique_constraint(
        'users_tenant_identity_number_key', 'users', ['tenant_id', 'identity_number']
    )
    op.create_unique_constraint('users_tenant_phone_number_key', 'users', ['tenant_id', 'phone_number'])


def downgrade() -> None:
    op.drop_constraint('users_tenant_phone_number_key', 'users', type_='unique')
    op.drop_constraint('users_tenant_identity_number_key', 'users', type_='unique')
    op.drop_constraint('users_tenant_email_key', 'users', type_='unique')
    op.create_unique_constraint('users_phone_number_key', 'users', ['phone_number'])
    op.create_unique_constraint('users_identity_number_key', 'users', ['identity_number'])
    op.create_unique_constraint('users_email_key', 'users', ['email'])

    op.drop_index(op.f('ix_system_logs_tenant_id'), table_name='system_logs')
    op.drop_constraint(op.f('fk_system_logs_tenant_id_tenants'), 'system_logs', type_='foreignkey')
    op.drop_column('system_logs', 'tenant_id')

    for table in reversed(_SCAPED_TABLES):
        op.drop_index(op.f(f'ix_{table}_tenant_id'), table_name=table)
        op.drop_constraint(op.f(f'fk_{table}_tenant_id_tenants'), table, type_='foreignkey')
        op.drop_column(table, 'tenant_id')