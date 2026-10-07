"""Pruebas de integración de los endpoints de configuración.

Cubren RBAC (solo superuser escribe), lectura de marca para autenticados y el
flujo SMTP/plantillas sin tocar MinIO (se mockea el logo).
"""

import pytest


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_branding_requires_auth(client):
    resp = await client.get("/api/v1/configuration/branding")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_branding_readable_by_any_authenticated(client, superuser_token):
    resp = await client.get(
        "/api/v1/configuration/branding", headers=_auth_headers(superuser_token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "dashboard_message" in body
    assert "organization_name" in body


@pytest.mark.asyncio
async def test_student_cannot_update_organization(client, student_token):
    resp = await client.put(
        "/api/v1/configuration/organization",
        headers=_auth_headers(student_token),
        json={"organization_name": "Hacked"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_superuser_updates_organization(client, superuser_token):
    resp = await client.put(
        "/api/v1/configuration/organization",
        headers=_auth_headers(superuser_token),
        json={"organization_name": "ACME", "dashboard_message": "Bienvenidos {{organization}}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["organization_name"] == "ACME"
    assert body["dashboard_message"] == "Bienvenidos ACME"

    read_resp = await client.get(
        "/api/v1/configuration/branding", headers=_auth_headers(superuser_token)
    )
    assert read_resp.json()["organization_name"] == "ACME"


@pytest.mark.asyncio
async def test_student_cannot_see_smtp(client, student_token):
    resp = await client.get(
        "/api/v1/configuration/email", headers=_auth_headers(student_token)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_smtp_password_never_returned(client, superuser_token):
    save = await client.put(
        "/api/v1/configuration/email",
        headers=_auth_headers(superuser_token),
        json={
            "smtp_enabled": True,
            "smtp_host": "smtp.acme.com",
            "smtp_port": 587,
            "smtp_user": "user",
            "smtp_password": "S3cret!",
            "clear_smtp_password": False,
            "smtp_tls": True,
            "email_from": "noreply@acme.com",
            "email_from_name": "ACME",
        },
    )
    assert save.status_code == 200, save.text
    body = save.json()
    assert body["smtp_password_set"] is True
    assert "S3cret!" not in save.text
    assert "smtp_password" not in body

    view = await client.get(
        "/api/v1/configuration/email", headers=_auth_headers(superuser_token)
    )
    assert view.status_code == 200
    assert "S3cret!" not in view.text
    assert view.json()["smtp_password_set"] is True


@pytest.mark.asyncio
async def test_smtp_clear_password(client, superuser_token):
    headers = _auth_headers(superuser_token)
    await client.put(
        "/api/v1/configuration/email",
        headers=headers,
        json={
            "smtp_enabled": True,
            "smtp_host": "smtp.acme.com",
            "smtp_port": 587,
            "smtp_user": "u",
            "smtp_password": "S3cret!",
            "clear_smtp_password": False,
            "smtp_tls": True,
            "email_from": None,
            "email_from_name": None,
        },
    )
    resp = await client.put(
        "/api/v1/configuration/email",
        headers=headers,
        json={
            "smtp_enabled": True,
            "smtp_host": "smtp.acme.com",
            "smtp_port": 587,
            "smtp_user": "u",
            "smtp_password": None,
            "clear_smtp_password": True,
            "smtp_tls": True,
            "email_from": None,
            "email_from_name": None,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["smtp_password_set"] is False


@pytest.mark.asyncio
async def test_email_templates_list_and_update(client, superuser_token):
    headers = _auth_headers(superuser_token)
    lst = await client.get("/api/v1/configuration/email/templates", headers=headers)
    assert lst.status_code == 200
    body = lst.json()
    assert len(body["items"]) == 3
    assert "placeholders" in body
    assert "student_name" in body["placeholders"]

    upd = await client.put(
        "/api/v1/configuration/email/templates/credentials",
        headers=headers,
        json={
            "subject": "Hola {{app_name}}",
            "body_html": "<p>Personalizado</p>",
            "is_enabled": True,
        },
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["is_custom"] is True
    assert upd.json()["subject"] == "Hola {{app_name}}"

    invalid = await client.put(
        "/api/v1/configuration/email/templates/nope",
        headers=headers,
        json={"subject": "x", "body_html": "<p>x</p>", "is_enabled": True},
    )
    assert invalid.status_code == 400


@pytest.mark.asyncio
async def test_email_template_restore(client, superuser_token):
    headers = _auth_headers(superuser_token)
    await client.put(
        "/api/v1/configuration/email/templates/certificate_expired",
        headers=headers,
        json={"subject": "Custom", "body_html": "<p>x</p>", "is_enabled": True},
    )
    resp = await client.delete(
        "/api/v1/configuration/email/templates/certificate_expired", headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["is_custom"] is False


@pytest.mark.asyncio
async def test_upload_logo_validates_image(client, superuser_token):
    resp = await client.post(
        "/api/v1/configuration/email/logo",
        headers=_auth_headers(superuser_token),
        files={"file": ("fake.txt", b"this is not an image", "text/plain")},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_logo_endpoints_mocked(client, superuser_token, monkeypatch):
    """El servicio de logo se mockea para no depender de MinIO."""
    from io import BytesIO

    from PIL import Image

    saved: dict = {}
    png_bytes = BytesIO()
    Image.new("RGB", (8, 8), color=(120, 60, 200)).save(png_bytes, format="PNG")

    async def fake_save(db, data, *, updated_by=None):
        saved["data"] = data

    async def fake_remove(db, *, updated_by=None):
        saved.pop("data", None)

    async def fake_get():
        return saved.get("data")

    import app.api.v1.endpoints.configuration as cfg_module

    monkeypatch.setattr(cfg_module.platform_settings_service, "save_logo", fake_save)
    monkeypatch.setattr(cfg_module.platform_settings_service, "remove_logo", fake_remove)
    monkeypatch.setattr(cfg_module.platform_settings_service, "get_logo_bytes", fake_get)

    headers = _auth_headers(superuser_token)
    upload = await client.post(
        "/api/v1/configuration/email/logo",
        headers=headers,
        files={"file": ("logo.png", png_bytes.getvalue(), "image/png")},
    )
    assert upload.status_code == 200, upload.text

    served = await client.get("/api/v1/configuration/branding/logo", headers=headers)
    assert served.status_code == 200
    assert served.content.startswith(b"\x89PNG")

    restored = await client.delete("/api/v1/configuration/email/logo", headers=headers)
    assert restored.status_code == 200
    assert "data" not in saved