"""Protección CSRF para autenticación por cookie."""

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_cookie_write_requires_csrf():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        login = await ac.post(
            "/api/v1/auth/token",
            data={
                "username": os.environ["SUPERUSER_EMAIL"],
                "password": os.environ["SUPERUSER_PASSWORD"],
            },
        )
        assert login.status_code == 200, login.text

        access = login.cookies.get("access_token")
        csrf = login.cookies.get("csrf_token")
        assert access, "El login debe emitir la cookie access_token"
        assert csrf, "El login debe emitir la cookie csrf_token"

        cookie_header = f"access_token={access}; csrf_token={csrf}"
        payload = {
            "title": f"CSRF {uuid.uuid4().hex[:8]}",
            "description": "prueba",
            "status": "draft",
        }

        blocked = await ac.post(
            "/api/v1/courses",
            json=payload,
            headers={"Cookie": cookie_header},
        )
        assert blocked.status_code == 403, blocked.text

        allowed = await ac.post(
            "/api/v1/courses",
            json=payload,
            headers={"Cookie": cookie_header, "X-CSRF-Token": csrf},
        )
        assert allowed.status_code == 201, allowed.text
