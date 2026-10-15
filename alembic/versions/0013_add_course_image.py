"""add course image

Revision ID: 0013_add_course_image
Revises: 0012_certificate_renewal
Create Date: 2026-10-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0013_add_course_image'
down_revision: Union[str, None] = '0012_certificate_renewal'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('courses', sa.Column('image_object_key', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('courses', 'image_object_key')
