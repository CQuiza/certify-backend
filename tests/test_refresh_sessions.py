"""Rotación, reuso y revocación de refresh tokens."""

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _cookie(name: str, value: str) -> dict[str, str]:
    return {"Cookie": f"{name}={value}"}


async def _login(ac: AsyncClient) -> tuple[str, str, str]:
    resp = await ac.post(
        "/api/v1/auth/token",
        data={
            "username": os.environ["SUPERUSER_EMAIL"],
            "password": os.environ["SUPERUSER_PASSWORD"],
        },
    )
    assert resp.status_code == 200, resp.text
    access = resp.cookies.get("access_token")
    refresh = resp.cookies.get("refresh_token")
    assert access and refresh
    return access, refresh, resp.json()["access_token"]


@pytest.mark.asyncio
async def test_refresh_rotation_and_reuse_detection():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        _, refresh, _ = await _login(ac)

        first = await ac.post("/api/v1/auth/refresh", headers=_cookie("refresh_token", refresh))
        assert first.status_code == 200, first.text
        rotated = first.cookies.get("refresh_token")
        assert rotated and rotated != refresh

        reuse = await ac.post(
            "/api/v1/auth/refresh", headers=_cookie("refresh_token", refresh)
        )
        assert reuse.status_code == 401, reuse.text

        revoked = await ac.post(
            "/api/v1/auth/refresh", headers=_cookie("refresh_token", rotated)
        )
        assert revoked.status_code == 401, revoked.text


@pytest.mark.asyncio
async def test_logout_revokes_refresh_session():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        _, refresh, _ = await _login(ac)

        logout = await ac.post("/api/v1/auth/logout", headers=_cookie("refresh_token", refresh))
        assert logout.status_code == 200, logout.text

        after = await ac.post(
            "/api/v1/auth/refresh", headers=_cookie("refresh_token", refresh)
        )
        assert after.status_code == 401, after.text


@pytest.mark.asyncio
async def test_password_change_revokes_all_sessions():
    email = f"refresh-{uuid.uuid4().hex[:8]}@example.com"
    password = "StrongPass1!"
    new_password = "NewStrongPass1!"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        register = await ac.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": password,
                "name": "Refresh",
                "first_last_name": "Test",
                "identity_type": "CC",
                "identity_number": f"REF-{uuid.uuid4().hex[:8]}",
                "phone_number": f"+57{uuid.uuid4().int % 10**10:010d}",
                "birth_date": "1990-01-01",
                "accepted_terms": True,
            },
        )
        assert register.status_code == 201, register.text
        access = register.json()["access_token"]
        refresh = register.cookies.get("refresh_token")
        assert refresh

        change = await ac.post(
            "/api/v1/users/change-password",
            headers={"Authorization": f"Bearer {access}"},
            json={"current_password": password, "new_password": new_password},
        )
        assert change.status_code == 200, change.text

        after = await ac.post(
            "/api/v1/auth/refresh", headers=_cookie("refresh_token", refresh)
        )
        assert after.status_code == 401, after.text
