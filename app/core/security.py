"""JWT, hashing de contraseñas y refresh tokens (OAuth2 compatible)."""

import hashlib
import secrets
import string
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import bcrypt
from jose import JWTError, jwt

from app.core.settings import get_settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def get_password_hash(password: str) -> str:
    """Hashea con bcrypt. El coste se controla con rounds (default 12)."""
    settings = get_settings()
    salt = bcrypt.gensalt(rounds=settings.bcrypt_rounds)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def create_access_token(
    subject: str | int,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    settings = get_settings()
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    expire = datetime.now(UTC) + expires_delta
    to_encode: dict[str, Any] = {
        "exp": expire,
        "sub": str(subject),
        "jti": str(uuid4()),
        "iat": datetime.now(UTC),
    }
    if extra_claims:
        to_encode.update(extra_claims)
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError as e:
        raise ValueError("Token inválido") from e


def generate_refresh_token() -> str:
    """Genera un token opaco (no-JWT) para refresh."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    """SHA-256 del refresh token para almacenar en BD."""
    return hashlib.sha256(token.encode()).hexdigest()


REFRESH_TOKEN_DAYS = 30


def refresh_token_expires_at() -> datetime:
    return datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_DAYS)


SPECIAL_CHARS = "!@#$%^&*()-_=+"


def generate_secure_password(length: int = 16) -> str:
    """Genera una contraseña criptográficamente segura que cumple las reglas de validación.

    Garantiza al menos: una mayúscula, una minúscula, un dígito y un carácter especial.
    """
    all_chars = string.ascii_letters + string.digits + SPECIAL_CHARS
    pw = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(SPECIAL_CHARS),
    ]
    pw += [secrets.choice(all_chars) for _ in range(length - 4)]
    secrets.SystemRandom().shuffle(pw)
    return "".join(pw)


def validate_password_strength(password: str) -> list[str]:
    """Valida que la contraseña cumpla los estándares OWASP 2023.

    Retorna lista de mensajes de error. Vacía si es válida.
    """
    errors: list[str] = []
    if len(password) < 8:
        errors.append("Debe tener al menos 8 caracteres")
    if not any(c.isupper() for c in password):
        errors.append("Debe contener al menos una letra mayúscula")
    if not any(c.islower() for c in password):
        errors.append("Debe contener al menos una letra minúscula")
    if not any(c.isdigit() for c in password):
        errors.append("Debe contener al menos un número")
    if not any(c in SPECIAL_CHARS for c in password):
        errors.append(f"Debe contener al menos un carácter especial ({SPECIAL_CHARS})")
    return errors
