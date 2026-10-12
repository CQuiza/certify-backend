"""add course pricing and payment orders

Revision ID: 0008_add_course_payments
Revises: 0007_add_task_grading
Create Date: 2026-10-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0008_add_course_payments'
down_revision: Union[str, None] = '0007_add_task_grading'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('courses', sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column('courses', sa.Column('is_for_sale', sa.Boolean(), server_default=sa.text('false'), nullable=False))

    op.create_table('course_orders',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('order_no', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('total', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('external_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_course_orders_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_course_orders')),
    sa.UniqueConstraint('order_no', name=op.f('uq_course_orders_order_no'))
    )
    op.create_index(op.f('ix_course_orders_external_id'), 'course_orders', ['external_id'], unique=False)
    op.create_table('course_order_items',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('order_id', sa.Integer(), nullable=False),
    sa.Column('course_id', sa.Integer(), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('course_title', sa.String(length=255), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], name=op.f('fk_course_order_items_course_id_courses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['order_id'], ['course_orders.id'], name=op.f('fk_course_order_items_order_id_course_orders'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_course_order_items')),
    sa.UniqueConstraint('order_id', 'course_id', name=op.f('uq_course_order_items_order_course'))
    )


def downgrade() -> None:
    op.drop_table('course_order_items')
    op.drop_index(op.f('ix_course_orders_external_id'), table_name='course_orders')
    op.drop_table('course_orders')
    op.drop_column('courses', 'is_for_sale')
    op.drop_column('courses', 'price')