"""Repositorio de usuarios."""

from collections.abc import Sequence

from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserRole
from app.models.user import User


class UserRepository:
    async def get_by_id(self, db: AsyncSession, user_id: int) -> User | None:
        r = await db.execute(select(User).where(User.id == user_id))
        return r.scalar_one_or_none()

    async def get_by_email(self, db: AsyncSession, email: str) -> User | None:
        r = await db.execute(select(User).where(User.email == email))
        return r.scalar_one_or_none()

    async def get_by_identity_number(self, db: AsyncSession, identity_number: str) -> User | None:
        r = await db.execute(select(User).where(User.identity_number == identity_number))
        return r.scalar_one_or_none()

    async def get_by_phone_number(self, db: AsyncSession, phone_number: str) -> User | None:
        r = await db.execute(select(User).where(User.phone_number == phone_number))
        return r.scalar_one_or_none()

    def _apply_filters(self, q, *, role, exclude_superuser, search):
        if role is not None:
            q = q.where(User.role == role.value)
        if exclude_superuser:
            q = q.where(User.role != UserRole.superuser.value)
        if search:
            pattern = f"%{search}%"
            q = q.where(
                User.name.ilike(pattern)
                | User.email.ilike(pattern)
                | User.identity_number.ilike(pattern)
            )
        return q

    async def count(
        self,
        db: AsyncSession,
        *,
        role: UserRole | None = None,
        exclude_superuser: bool = False,
        search: str | None = None,
    ) -> int:
        q = select(func.count(User.id))
        q = self._apply_filters(q, role=role, exclude_superuser=exclude_superuser, search=search)
        r = await db.execute(q)
        return r.scalar() or 0

    async def list(
        self,
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 100,
        role: UserRole | None = None,
        exclude_superuser: bool = False,
        search: str | None = None,
    ) -> Sequence[User]:
        q = select(User).offset(skip).limit(limit)
        q = self._apply_filters(q, role=role, exclude_superuser=exclude_superuser, search=search)
        r = await db.execute(q.order_by(User.id))
        return r.scalars().all()

    async def create(
        self,
        db: AsyncSession,
        *,
        email: str,
        password_hash: str,
        name: str | None,
        first_last_name: str | None,
        second_last_name: str | None,
        role: str,
        identity_type: str,
        identity_number: str,
        phone_number: str,
        is_active: bool = True,
    ) -> User:
        u = User(
            email=email,
            password_hash=password_hash,
            name=name,
            first_last_name=first_last_name,
            second_last_name=second_last_name,
            role=role,
            identity_type=identity_type,
            identity_number=identity_number,
            phone_number=phone_number,
            is_active=is_active,
        )
        db.add(u)
        await db.flush()
        await db.refresh(u)
        return u

    async def update(self, db: AsyncSession, user: User, fields: dict[str, object]) -> User:
        allowed = {
            "email",
            "password_hash",
            "name",
            "first_last_name",
            "second_last_name",
            "role",
            "identity_type",
            "identity_number",
            "phone_number",
            "is_active",
        }
        for k, v in fields.items():
            if k in allowed:
                setattr(user, k, v)
        await db.flush()
        await db.refresh(user)
        return user

    async def count_certified_students(
        self,
        db: AsyncSession,
        *,
        search: str | None = None,
    ) -> int:
        from app.models.certificate import Certificate
        from app.models.certificate_type import CertificateType

        q = (
            select(func.count(User.id.distinct()))
            .select_from(User)
            .join(Certificate, User.id == Certificate.user_id)
            .where(User.role == UserRole.student.value)
        )
        if search:
            pattern = f"%{search}%"
            q = q.outerjoin(CertificateType, Certificate.certificate_type_id == CertificateType.id)
            q = q.where(
                User.name.ilike(pattern)
                | User.email.ilike(pattern)
                | User.identity_number.ilike(pattern)
                | cast(Certificate.unique_id, String).ilike(pattern)
                | CertificateType.name.ilike(pattern)
            )
        r = await db.execute(q)
        return r.scalar() or 0

    async def list_certified_students(
        self,
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 100,
        search: str | None = None,
    ) -> Sequence[User]:
        from sqlalchemy.orm import selectinload
        from app.models.certificate import Certificate
        from app.models.certificate_type import CertificateType

        q = (
            select(User)
            .join(Certificate, User.id == Certificate.user_id)
            .where(User.role == UserRole.student.value)
            .distinct()
            .options(selectinload(User.certificates))
        )
        if search:
            pattern = f"%{search}%"
            q = q.outerjoin(CertificateType, Certificate.certificate_type_id == CertificateType.id)
            q = q.where(
                User.name.ilike(pattern)
                | User.email.ilike(pattern)
                | User.identity_number.ilike(pattern)
                | cast(Certificate.unique_id, String).ilike(pattern)
                | CertificateType.name.ilike(pattern)
            )
        q = q.offset(skip).limit(limit)
        r = await db.execute(q.order_by(User.id))
        return r.scalars().all()

    async def delete(self, db: AsyncSession, user: User) -> None:
        await db.delete(user)


user_repository = UserRepository()

