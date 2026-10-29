"""add birth date to users

Revision ID: 0020_user_birth_date
Revises: 0019_refresh_tenant_idx
"""

import sqlalchemy as sa
from alembic import op

revision = "0020_user_birth_date"
down_revision = "0019_refresh_tenant_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("birth_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "birth_date")
