"""create refresh sessions and RLS policy

Revision ID: 0016_refresh_sessions
Revises: 0015_add_rls
"""

import sqlalchemy as sa
from alembic import op

from app.core.settings import get_settings

revision = "0016_refresh_sessions"
down_revision = "0015_add_rls"
branch_labels = None
depends_on = None


def _grant(table: str, sequence: str, privileges: str = "SELECT, INSERT, UPDATE, DELETE") -> None:
    role = get_settings().app_db_role.strip()
    if not role:
        return
    op.execute(f'GRANT {privileges} ON "{table}" TO "{role}"')
    op.execute(f'GRANT USAGE, SELECT ON SEQUENCE "{sequence}" TO "{role}"')


def upgrade() -> None:
    op.create_table(
        "refresh_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("family_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(length=50), nullable=True),
        sa.Column("replaced_by_id", sa.Integer(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["replaced_by_id"], ["refresh_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_refresh_sessions_user_id", "refresh_sessions", ["user_id"])
    op.create_index("ix_refresh_sessions_family_id", "refresh_sessions", ["family_id"])

    op.execute("ALTER TABLE refresh_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE refresh_sessions FORCE ROW LEVEL SECURITY")
    policy = """
        current_setting('app.rls_bypass', true) = 'on'
        OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::integer
    """
    op.execute(
        f'CREATE POLICY tenant_isolation ON refresh_sessions USING ({policy}) '
        f"WITH CHECK ({policy})"
    )
    _grant("refresh_sessions", "refresh_sessions_id_seq")


def downgrade() -> None:
    op.drop_index("ix_refresh_sessions_family_id", table_name="refresh_sessions")
    op.drop_index("ix_refresh_sessions_user_id", table_name="refresh_sessions")
    op.drop_table("refresh_sessions")
