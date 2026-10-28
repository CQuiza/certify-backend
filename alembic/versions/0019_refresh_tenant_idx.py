"""add tenant index to refresh sessions

Revision ID: 0019_refresh_tenant_idx
Revises: 0018_payment_webhook_events
"""

from alembic import op

revision = "0019_refresh_tenant_idx"
down_revision = "0018_payment_webhook_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_refresh_sessions_tenant_id",
        "refresh_sessions",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_refresh_sessions_tenant_id",
        table_name="refresh_sessions",
    )
