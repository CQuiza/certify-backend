"""create global security audit table

Revision ID: 0017_security_audit
Revises: 0016_refresh_sessions
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.settings import get_settings

revision = "0017_security_audit"
down_revision = "0016_refresh_sessions"
branch_labels = None
depends_on = None


def _grant(table: str, sequence: str) -> None:
    role = get_settings().app_db_role.strip()
    if not role:
        return
    op.execute(f'GRANT SELECT, INSERT ON "{table}" TO "{role}"')
    op.execute(f'GRANT USAGE, SELECT ON SEQUENCE "{sequence}" TO "{role}"')


def upgrade() -> None:
    op.create_table(
        "security_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_role", sa.String(length=50), nullable=True),
        sa.Column("target_tenant_id", sa.Integer(), nullable=True),
        sa.Column("target_type", sa.String(length=50), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_security_audit_action", "security_audit", ["action"])
    op.create_index(
        "ix_security_audit_target_tenant_id", "security_audit", ["target_tenant_id"]
    )
    op.create_index("ix_security_audit_created_at", "security_audit", ["created_at"])
    _grant("security_audit", "security_audit_id_seq")


def downgrade() -> None:
    op.drop_index("ix_security_audit_created_at", table_name="security_audit")
    op.drop_index("ix_security_audit_target_tenant_id", table_name="security_audit")
    op.drop_index("ix_security_audit_action", table_name="security_audit")
    op.drop_table("security_audit")
