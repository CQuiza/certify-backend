"""create payment webhook event deduplication table

Revision ID: 0018_payment_webhook_events
Revises: 0017_security_audit
"""

import sqlalchemy as sa
from alembic import op

from app.core.settings import get_settings

revision = "0018_payment_webhook_events"
down_revision = "0017_security_audit"
branch_labels = None
depends_on = None


def _grant(table: str, sequence: str) -> None:
    role = get_settings().app_db_role.strip()
    if not role:
        return
    op.execute(f'GRANT SELECT, INSERT, UPDATE ON "{table}" TO "{role}"')
    op.execute(f'GRANT USAGE, SELECT ON SEQUENCE "{sequence}" TO "{role}"')


def upgrade() -> None:
    op.create_table(
        "payment_webhook_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("payment_id", sa.String(length=64), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["order_id"], ["course_orders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_id"),
    )
    op.create_index(
        "ix_payment_webhook_events_order_id", "payment_webhook_events", ["order_id"]
    )
    _grant("payment_webhook_events", "payment_webhook_events_id_seq")


def downgrade() -> None:
    op.drop_index(
        "ix_payment_webhook_events_order_id", table_name="payment_webhook_events"
    )
    op.drop_table("payment_webhook_events")
