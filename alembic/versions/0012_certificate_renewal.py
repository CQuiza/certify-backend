"""certificate renewal lifecycle (course link, renewal flags, renewal price)

Revision ID: 0012_certificate_renewal
Revises: 0011_add_tenant_contacts
Create Date: 2026-10-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0012_certificate_renewal'
down_revision: Union[str, None] = '0011_add_tenant_contacts'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('courses', sa.Column('renewal_price', sa.Numeric(precision=10, scale=2), nullable=True))

    op.add_column('certificates', sa.Column('course_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f('fk_certificates_course_id_courses'),
        'certificates', 'courses', ['course_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index(op.f('ix_certificates_course_id'), 'certificates', ['course_id'], unique=False)
    # Backfill: certificado -> curso desde la solicitud que lo emitió.
    op.execute(
        "UPDATE certificates c SET course_id = pc.course_id "
        "FROM pending_certificates pc WHERE pc.issued_certificate_id = c.id AND c.course_id IS NULL"
    )

    op.add_column('pending_certificates', sa.Column('renewal_of_certificate_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f('fk_pending_certificates_renewal_of_certificate_id_certificates'),
        'pending_certificates', 'certificates', ['renewal_of_certificate_id'], ['id'], ondelete='SET NULL',
    )

    op.add_column('course_orders', sa.Column('kind', sa.String(length=20), server_default=sa.text("'course'"), nullable=False))
    op.add_column('course_orders', sa.Column('renewal_certificate_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f('fk_course_orders_renewal_certificate_id_certificates'),
        'course_orders', 'certificates', ['renewal_certificate_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(op.f('fk_course_orders_renewal_certificate_id_certificates'), 'course_orders', type_='foreignkey')
    op.drop_column('course_orders', 'renewal_certificate_id')
    op.drop_column('course_orders', 'kind')

    op.drop_constraint(op.f('fk_pending_certificates_renewal_of_certificate_id_certificates'), 'pending_certificates', type_='foreignkey')
    op.drop_column('pending_certificates', 'renewal_of_certificate_id')

    op.drop_index(op.f('ix_certificates_course_id'), table_name='certificates')
    op.drop_constraint(op.f('fk_certificates_course_id_courses'), 'certificates', type_='foreignkey')
    op.drop_column('certificates', 'course_id')

    op.drop_column('courses', 'renewal_price')