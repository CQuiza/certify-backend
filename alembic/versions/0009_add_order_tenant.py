"""add tenant_id to course_orders and course_order_items

Revision ID: 0009_add_order_tenant
Revises: 0008_add_course_payments
Create Date: 2026-10-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0009_add_order_tenant'
down_revision: Union[str, None] = '0008_add_course_payments'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('course_orders', sa.Column('tenant_id', sa.Integer(), nullable=True))
    op.execute(
        "UPDATE course_orders SET tenant_id = "
        "(SELECT users.tenant_id FROM users WHERE users.id = course_orders.user_id)"
    )
    op.alter_column('course_orders', 'tenant_id', existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key(
        op.f('fk_course_orders_tenant_id_tenants'),
        'course_orders', 'tenants', ['tenant_id'], ['id'], ondelete='CASCADE',
    )
    op.create_index(op.f('ix_course_orders_tenant_id'), 'course_orders', ['tenant_id'], unique=False)

    op.add_column('course_order_items', sa.Column('tenant_id', sa.Integer(), nullable=True))
    op.execute(
        "UPDATE course_order_items SET tenant_id = "
        "(SELECT course_orders.tenant_id FROM course_orders WHERE course_orders.id = course_order_items.order_id)"
    )
    op.alter_column('course_order_items', 'tenant_id', existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key(
        op.f('fk_course_order_items_tenant_id_tenants'),
        'course_order_items', 'tenants', ['tenant_id'], ['id'], ondelete='CASCADE',
    )
    op.create_index(op.f('ix_course_order_items_tenant_id'), 'course_order_items', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_course_order_items_tenant_id'), table_name='course_order_items')
    op.drop_constraint(
        op.f('fk_course_order_items_tenant_id_tenants'), 'course_order_items', type_='foreignkey'
    )
    op.drop_column('course_order_items', 'tenant_id')

    op.drop_index(op.f('ix_course_orders_tenant_id'), table_name='course_orders')
    op.drop_constraint(
        op.f('fk_course_orders_tenant_id_tenants'), 'course_orders', type_='foreignkey'
    )
    op.drop_column('course_orders', 'tenant_id')