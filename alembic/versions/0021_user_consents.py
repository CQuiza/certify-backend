"""create user legal consents

Revision ID: 0021_user_consents
Revises: 0020_user_birth_date
"""

import sqlalchemy as sa
from alembic import op

from app.core.settings import get_settings

revision = "0021_user_consents"
down_revision = "0020_user_birth_date"
branch_labels = None
depends_on = None


def _grant(table: str, sequence: str) -> None:
    role = get_settings().app_db_role.strip()
    if not role:
        return
    op.execute(f'GRANT SELECT, INSERT, DELETE ON "{table}" TO "{role}"')
    op.execute(f'GRANT USAGE, SELECT ON SEQUENCE "{sequence}" TO "{role}"')


def upgrade() -> None:
    op.create_table(
        "user_consents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("document", sa.String(length=50), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "document",
            "version",
            name="user_consents_user_document_version_key",
        ),
    )
    op.create_index("ix_user_consents_tenant_id", "user_consents", ["tenant_id"])
    op.create_index("ix_user_consents_user_id", "user_consents", ["user_id"])
    op.create_index("ix_user_consents_document", "user_consents", ["document"])

    op.execute("ALTER TABLE user_consents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_consents FORCE ROW LEVEL SECURITY")
    policy = """
        current_setting('app.rls_bypass', true) = 'on'
        OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::integer
    """
    op.execute(
        "CREATE POLICY tenant_isolation ON user_consents "
        f"USING ({policy}) WITH CHECK ({policy})"
    )
    _grant("user_consents", "user_consents_id_seq")


def downgrade() -> None:
    op.drop_index("ix_user_consents_document", table_name="user_consents")
    op.drop_index("ix_user_consents_user_id", table_name="user_consents")
    op.drop_index("ix_user_consents_tenant_id", table_name="user_consents")
    op.drop_table("user_consents")
