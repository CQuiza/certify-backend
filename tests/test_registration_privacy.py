"""PRIV-02: el registro no debe revelar qué identificador existe."""

import uuid
from datetime import date

import pytest

from app.services import turnstile_service

GENERIC_DETAIL = "No pudimos completar el registro. Intenta de nuevo o inicia sesión."


def _payload() -> dict[str, str]:
    suffix = uuid.uuid4().hex[:10]
    return {
        "email": f"privacy-{suffix}@example.com",
        "password": "StrongPass1!",
        "name": "Privacy",
        "first_last_name": "Test",
        "identity_type": "CC",
        "identity_number": f"PRIV-{suffix}",
        "phone_number": f"+57{uuid.uuid4().int % 10**10:010d}",
        "birth_date": "1990-01-01",
        "accepted_terms": True,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["email", "identity_number", "phone_number"])
async def test_duplicate_identifier_returns_generic_error(client, field):
    first = _payload()
    created = await client.post("/api/v1/auth/register", json=first)
    assert created.status_code == 201, created.text

    duplicate = _payload() | {field: first[field]}
    response = await client.post("/api/v1/auth/register", json=duplicate)
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == GENERIC_DETAIL


@pytest.mark.asyncio
async def test_captcha_failure_uses_the_same_generic_error(client, monkeypatch):
    async def _reject(_token: str | None) -> bool:
        return False

    monkeypatch.setattr(turnstile_service, "verify_token", _reject)

    response = await client.post("/api/v1/auth/register", json=_payload())
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == GENERIC_DETAIL


@pytest.mark.asyncio
async def test_registration_is_rate_limited(client):
    statuses = []
    for _ in range(4):
        response = await client.post("/api/v1/auth/register", json=_payload())
        statuses.append(response.status_code)

    assert statuses[:3] == [201, 201, 201]
    assert statuses[3] == 429


@pytest.mark.asyncio
async def test_registration_rejects_underage_user(client):
    today = date.today()
    payload = _payload() | {"birth_date": date(today.year - 17, 1, 1).isoformat()}

    response = await client.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "Debes ser mayor de 18 años para registrarte."


@pytest.mark.asyncio
async def test_registration_accepts_adult_user(client):
    today = date.today()
    payload = _payload() | {"birth_date": date(today.year - 18, 1, 1).isoformat()}

    response = await client.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 201, response.text
