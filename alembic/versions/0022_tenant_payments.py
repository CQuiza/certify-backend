"""create tenant payments (cobranza SaaS)

Revision ID: 0022_tenant_payments
Revises: 0021_user_consents
"""

import sqlalchemy as sa
from alembic import op

from app.core.settings import get_settings

revision = "0022_tenant_payments"
down_revision = "0021_user_consents"
branch_labels = None
depends_on = None


def _grant(table: str, sequence: str) -> None:
    role = get_settings().app_db_role.strip()
    if not role:
        return
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO "{role}"')
    op.execute(f'GRANT USAGE, SELECT ON SEQUENCE "{sequence}" TO "{role}"')


def upgrade() -> None:
    op.create_table(
        "tenant_payments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("plan", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=10),
            server_default="COP",
            nullable=False,
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("paid_at", sa.Date(), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tenant_payments_tenant_period_end",
        "tenant_payments",
        ["tenant_id", "period_end"],
    )
    _grant("tenant_payments", "tenant_payments_id_seq")


def downgrade() -> None:
    op.drop_index(
        "ix_tenant_payments_tenant_period_end", table_name="tenant_payments"
    )
    op.drop_table("tenant_payments")
