"""add task grading fields to task_submissions

Revision ID: 0007_add_task_grading
Revises: 0006_add_tenant_columns
Create Date: 2026-10-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007_add_task_grading'
down_revision: Union[str, None] = '0006_add_tenant_columns'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('task_submissions', sa.Column('score', sa.Numeric(precision=5, scale=2), nullable=True))
    op.add_column('task_submissions', sa.Column('feedback', sa.Text(), nullable=True))
    op.add_column('task_submissions', sa.Column('passed', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('task_submissions', sa.Column('graded_by', sa.Integer(), nullable=True))
    op.add_column('task_submissions', sa.Column('graded_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        op.f('fk_task_submissions_graded_by_users'),
        'task_submissions', 'users', ['graded_by'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f('fk_task_submissions_graded_by_users'), 'task_submissions', type_='foreignkey'
    )
    op.drop_column('task_submissions', 'graded_at')
    op.drop_column('task_submissions', 'graded_by')
    op.drop_column('task_submissions', 'passed')
    op.drop_column('task_submissions', 'feedback')
    op.drop_column('task_submissions', 'score')