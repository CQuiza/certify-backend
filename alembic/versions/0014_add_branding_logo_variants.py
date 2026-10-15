"""add branding logo variants (dark, surface, is_dark)

Revision ID: 0014_branding_logo_variants
Revises: 0013_add_course_image
Create Date: 2026-10-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0014_branding_logo_variants'
down_revision: Union[str, None] = '0013_add_course_image'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'platform_settings',
        sa.Column('branding_logo_dark_object_key', sa.String(length=255), nullable=True),
    )
    op.add_column(
        'platform_settings',
        sa.Column(
            'branding_logo_surface',
            sa.String(length=10),
            server_default='auto',
            nullable=False,
        ),
    )
    op.add_column(
        'platform_settings',
        sa.Column(
            'branding_logo_is_dark',
            sa.Boolean(),
            server_default=sa.text('false'),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column('platform_settings', 'branding_logo_is_dark')
    op.drop_column('platform_settings', 'branding_logo_surface')
    op.drop_column('platform_settings', 'branding_logo_dark_object_key')
