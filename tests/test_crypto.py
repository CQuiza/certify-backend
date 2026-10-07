"""Pruebas del cifrado de secretos (SMTP)."""

from app.core.crypto import decrypt_secret, encrypt_secret, password_is_set


def test_round_trip():
    token = encrypt_secret("Super Secret 123!")
    assert token != "Super Secret 123!"
    assert decrypt_secret(token) == "Super Secret 123!"


def test_deterministic_ciphertext_not_equal_plain():
    a = encrypt_secret("abc")
    b = encrypt_secret("abc")
    # Fernet es aleatorio: dos cifrados del mismo valor difieren.
    assert a != b
    assert decrypt_secret(a) == decrypt_secret(b) == "abc"


def test_decrypt_none_or_empty():
    assert decrypt_secret(None) is None
    assert decrypt_secret("") is None


def test_password_is_set():
    assert password_is_set(None) is False
    assert password_is_set(encrypt_secret("x")) is True


def test_decrypt_garbage_returns_none():
    assert decrypt_secret("not-a-valid-token") is None