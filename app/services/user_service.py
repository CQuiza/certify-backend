"""Usuarios y credenciales."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash, verify_password
from app.models.user import User
from app.repositories.user_repository import user_repository
from app.schemas.user import UserCreate, UserUpdate


class UserService:
    async def authenticate(self, db: AsyncSession, email: str, password: str) -> User | None:
        user = await user_repository.get_by_email(db, email)
        if not user or not user.is_active:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user

    async def create_user(self, db: AsyncSession, data: UserCreate) -> User:
        existing = await user_repository.get_by_email(db, data.email)
        if existing:
            raise ValueError("El correo ya está registrado")
        hashed = get_password_hash(data.password)
        return await user_repository.create(
            db,
            email=data.email,
            password_hash=hashed,
            name=data.name,
            first_last_name=data.first_last_name,
            second_last_name=data.second_last_name,
            role=data.role.value,
            identity_type=data.identity_type.value,
            identity_number=data.identity_number,
            phone_number=data.phone_number,
            is_active=data.is_active,
        )

    async def update_user(self, db: AsyncSession, user: User, data: UserUpdate) -> User:
        payload = data.model_dump(exclude_unset=True)
        if "password" in payload:
            payload["password_hash"] = get_password_hash(payload.pop("password"))
        if "role" in payload and payload["role"] is not None:
            payload["role"] = payload["role"].value
        if "identity_type" in payload and payload["identity_type"] is not None:
            payload["identity_type"] = payload["identity_type"].value
        return await user_repository.update(db, user, payload)


user_service = UserService()
