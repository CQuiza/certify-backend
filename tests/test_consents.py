"""Consentimiento EULA: registro, bloqueo y aceptación."""

import uuid

import pytest

from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.core.tenant import resolve_default_tenant_id
from app.models.user import User


async def _pending_student() -> tuple[str, str]:
    email = f"pending-{uuid.uuid4().hex[:8]}@example.com"
    password = "PendingPass1!"
    async with AsyncSessionLocal() as session:
        tenant_id = await resolve_default_tenant_id(session)
        session.add(
            User(
                email=email,
                password_hash=get_password_hash(password),
                name="Pending",
                first_last_name="Student",
                role="student",
                identity_type="CC",
                identity_number=f"PEND-{uuid.uuid4().hex[:8]}",
                phone_number=f"+57{uuid.uuid4().int % 10**10:010d}",
                is_active=True,
                tenant_id=tenant_id,
            )
        )
        await session.commit()
    return email, password


@pytest.mark.asyncio
async def test_student_without_eula_is_blocked_until_accepting(client):
    email, password = await _pending_student()

    login = await client.post(
        "/api/v1/auth/token",
        data={"username": email, "password": password},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["eula_pending"] is True
    assert me.json()["eula_version"]

    blocked = await client.get("/api/v1/certificates", headers=headers)
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["detail"]["code"] == "consent_required"

    accepted = await client.post("/api/v1/auth/accept-eula", headers=headers)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["accepted"] is True

    me_after = await client.get("/api/v1/auth/me", headers=headers)
    assert me_after.status_code == 200, me_after.text
    assert me_after.json()["eula_pending"] is False

    allowed = await client.get("/api/v1/certificates", headers=headers)
    assert allowed.status_code == 200, allowed.text


@pytest.mark.asyncio
async def test_registration_requires_terms_acceptance(client):
    suffix = uuid.uuid4().hex[:8]
    payload = {
        "email": f"terms-{suffix}@example.com",
        "password": "StrongPass1!",
        "name": "Terms",
        "first_last_name": "Test",
        "identity_type": "CC",
        "identity_number": f"TERMS-{suffix}",
        "phone_number": f"+57{uuid.uuid4().int % 10**10:010d}",
        "birth_date": "1990-01-01",
    }

    rejected = await client.post("/api/v1/auth/register", json=payload)
    assert rejected.status_code == 400, rejected.text

    accepted_payload = payload | {"accepted_terms": True}
    created = await client.post("/api/v1/auth/register", json=accepted_payload)
    assert created.status_code == 201, created.text

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select

        from app.models.user_consent import UserConsent

        user = (
            await session.execute(
                select(User).where(User.email == accepted_payload["email"])
            )
        ).scalar_one()
        row = (
            await session.execute(
                select(UserConsent).where(
                    UserConsent.user_id == user.id,
                    UserConsent.document == "eula_students",
                )
            )
        ).scalar_one()
        assert row.accepted_at is not None
        assert row.version
