"""Turnstile en login y búsqueda pública."""

from types import SimpleNamespace

import pytest

from app.services import turnstile_service

GENERIC_LOGIN_DETAIL = "Credenciales incorrectas"
GENERIC_SEARCH_DETAIL = "No se encontraron certificados para esta identidad"

SUPERUSER_EMAIL = "super@example.com"
SUPERUSER_PASSWORD = "TestPassw0rd!!"


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    payload: dict = {}

    def __init__(self, **_kwargs) -> None:
        return None

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False

    async def post(self, *_args, **_kwargs) -> _FakeResponse:
        return _FakeResponse(type(self).payload)


def _configure(monkeypatch, payload: dict) -> None:
    class Client(_FakeClient):
        pass

    Client.payload = payload
    monkeypatch.setattr(turnstile_service.httpx, "AsyncClient", Client)
    monkeypatch.setattr(
        turnstile_service,
        "get_settings",
        lambda: SimpleNamespace(turnstile_secret_key="secret", environment="production"),
    )


@pytest.mark.asyncio
async def test_verify_token_accepts_expected_action(monkeypatch):
    _configure(monkeypatch, {"success": True, "action": "login"})

    assert await turnstile_service.verify_token("token", "login") is True


@pytest.mark.asyncio
async def test_verify_token_rejects_other_action(monkeypatch):
    _configure(monkeypatch, {"success": True, "action": "login"})

    assert await turnstile_service.verify_token("token", "search") is False


@pytest.mark.asyncio
async def test_verify_token_rejects_missing_action(monkeypatch):
    _configure(monkeypatch, {"success": True})

    assert await turnstile_service.verify_token("token", "login") is False


@pytest.mark.asyncio
async def test_verify_token_rejects_failed_challenge(monkeypatch):
    _configure(monkeypatch, {"success": False, "action": "login"})

    assert await turnstile_service.verify_token("token", "login") is False


@pytest.mark.asyncio
async def test_login_rejects_when_captcha_fails(client, monkeypatch):
    async def _reject(_token: str | None, _action: str = "register") -> bool:
        return False

    monkeypatch.setattr(turnstile_service, "verify_token", _reject)

    response = await client.post(
        "/api/v1/auth/token",
        data={"username": SUPERUSER_EMAIL, "password": SUPERUSER_PASSWORD},
    )

    assert response.status_code == 401, response.text
    assert response.json()["detail"] == GENERIC_LOGIN_DETAIL


@pytest.mark.asyncio
async def test_login_verifies_captcha_with_login_action(client, monkeypatch):
    captured: list[tuple[str | None, str]] = []

    async def _accept(token: str | None, action: str = "register") -> bool:
        captured.append((token, action))
        return True

    monkeypatch.setattr(turnstile_service, "verify_token", _accept)

    response = await client.post(
        "/api/v1/auth/token",
        data={"username": SUPERUSER_EMAIL, "password": SUPERUSER_PASSWORD},
        headers={"X-Turnstile-Token": "login-token"},
    )

    assert response.status_code == 200, response.text
    assert captured == [("login-token", "login")]


@pytest.mark.asyncio
async def test_search_rejects_when_captcha_fails(client, monkeypatch):
    async def _reject(_token: str | None, _action: str = "register") -> bool:
        return False

    monkeypatch.setattr(turnstile_service, "verify_token", _reject)

    response = await client.get("/api/v1/certificates/search-by-identity/9090909090")

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == GENERIC_SEARCH_DETAIL


@pytest.mark.asyncio
async def test_search_verifies_captcha_with_search_action(client, monkeypatch):
    captured: list[tuple[str | None, str]] = []

    async def _accept(token: str | None, action: str = "register") -> bool:
        captured.append((token, action))
        return True

    monkeypatch.setattr(turnstile_service, "verify_token", _accept)

    response = await client.get(
        "/api/v1/certificates/search-by-identity/9090909090",
        headers={"X-Turnstile-Token": "search-token"},
    )

    # No hay certificados para esa identidad: el 404 es del flujo normal.
    assert response.status_code == 404, response.text
    assert captured == [("search-token", "search")]
