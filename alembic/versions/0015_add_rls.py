"""add PostgreSQL row level security for tenant data

Revision ID: 0015_add_rls
Revises: 0014_branding_logo_variants
"""

from alembic import op

revision = "0015_add_rls"
down_revision = "0014_branding_logo_variants"
branch_labels = None
depends_on = None

_TENANT_TABLES = (
    "users",
    "courses",
    "course_enrollments",
    "modules",
    "lessons",
    "lesson_files",
    "lesson_tasks",
    "task_submissions",
    "module_assessments",
    "assessment_questions",
    "assessment_options",
    "user_assessment_attempts",
    "user_assessment_answers",
    "user_progress",
    "certificates",
    "certificate_types",
    "certificate_audit",
    "pending_certificates",
    "course_orders",
    "course_order_items",
    "email_audit",
    "user_audit",
    "platform_settings",
)

_TENANT_POLICY = """
    current_setting('app.rls_bypass', true) = 'on'
    OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::integer
"""

_EMAIL_TEMPLATE_POLICY = """
    current_setting('app.rls_bypass', true) = 'on'
    OR EXISTS (
        SELECT 1
        FROM platform_settings ps
        WHERE ps.id = email_templates.platform_settings_id
          AND ps.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::integer
    )
"""


def _enable_rls(table: str, policy: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
    op.execute(
        f'CREATE POLICY tenant_isolation ON "{table}" '
        f"USING ({policy}) WITH CHECK ({policy})"
    )


def _disable_rls(table: str) -> None:
    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
    op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


def upgrade() -> None:
    for table in _TENANT_TABLES:
        _enable_rls(table, _TENANT_POLICY)
    _enable_rls("email_templates", _EMAIL_TEMPLATE_POLICY)


def downgrade() -> None:
    _disable_rls("email_templates")
    for table in reversed(_TENANT_TABLES):
        _disable_rls(table)
