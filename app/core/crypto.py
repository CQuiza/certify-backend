"""Cifrado simétrico de secretos (contraseña SMTP).

Usa Fernet con una clave derivada de ``SECRET_KEY``. Nunca se loguea ni se
devuelve la contraseña por la API; el descifrado de un token inválido (p. ej.
tras rotar ``SECRET_KEY``) devuelve ``None`` para degradar al fallback del .env.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.settings import get_settings


def _fernet() -> Fernet:
    settings = get_settings()
    digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plain: str) -> str:
    if plain is None:
        raise ValueError("No se puede cifrar un valor vacío")
    return _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        # La clave rotó o el token está corrupto: tratamos como no configurado.
        return None


def password_is_set(token: str | None) -> bool:
    return bool(token and decrypt_secret(token))