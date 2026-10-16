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
    assert "contact_phone" in body
    assert "contact_email" in body


@pytest.mark.asyncio
async def test_public_branding_no_auth_and_contacts(client, superuser_token):
    # Sin autenticación debe responder.
    resp = await client.get("/api/v1/configuration/public")
    assert resp.status_code == 200
    assert set(resp.json().keys()) >= {"organization_name", "contact_phone", "contact_email"}

    # Guardar contactos (superuser) y verificar que se reflejan en público y branding.
    put = await client.put(
        "/api/v1/configuration/organization",
        headers=_auth_headers(superuser_token),
        json={
            "organization_name": "Org Contacto",
            "dashboard_message": None,
            "contact_phone": "+57 300 111 2233",
            "contact_email": "hola@org.example",
        },
    )
    assert put.status_code == 200, put.text
    assert put.json()["contact_phone"] == "+57 300 111 2233"
    assert put.json()["contact_email"] == "hola@org.example"

    pub = await client.get("/api/v1/configuration/public")
    assert pub.json()["contact_phone"] == "+57 300 111 2233"
    assert pub.json()["contact_email"] == "hola@org.example"

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
    assert len(body["items"]) == 4  # credenciales, emitido, expirado, compra
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
async def test_payments_settings_superuser_only(client, superuser_token, student_token):
    headers = _auth_headers(superuser_token)

    got = await client.get("/api/v1/configuration/payments", headers=headers)
    assert got.status_code == 200, got.text
    assert got.json()["mercadopago_enabled"] is False
    assert got.json()["currency"] == "COP"

    denied = await client.get("/api/v1/configuration/payments", headers=_auth_headers(student_token))
    assert denied.status_code == 403

    put = await client.put(
        "/api/v1/configuration/payments",
        headers=headers,
        json={"mercadopago_enabled": True, "mercadopago_marketplace_user_id": "MP_USER_1"},
    )
    assert put.status_code == 200, put.text
    assert put.json()["mercadopago_enabled"] is True
    assert put.json()["mercadopago_marketplace_user_id"] == "MP_USER_1"


@pytest.mark.asyncio
async def test_payments_settings_auth_required(client):
    resp = await client.get("/api/v1/configuration/payments")
    assert resp.status_code == 401


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

    # Simulamos MinIO configurado (los tests limpian las claves).
    from app.core.settings import get_settings

    _s = get_settings()
    monkeypatch.setattr(_s, "minio_access_key", "test")
    monkeypatch.setattr(_s, "minio_secret_key", "test")

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


@pytest.mark.asyncio
async def test_branding_logo_variants(client, superuser_token, monkeypatch):
    """Logo principal (luminancia), logo oscuro y superficie se persisten y sirven."""
    from io import BytesIO

    from PIL import Image

    from app.core.settings import get_settings
    import app.utils.minio_client as minio_module

    _s = get_settings()
    monkeypatch.setattr(_s, "minio_access_key", "test")
    monkeypatch.setattr(_s, "minio_secret_key", "test")

    store: dict[str, bytes] = {}

    class FakeMinio:
        def ensure_bucket(self):  # noqa: D401
            return None

        def upload_bytes(self, object_name, data, *, content_type):  # noqa: ANN001
            store[object_name] = data

        def download_bytes(self, object_name):  # noqa: ANN001
            return store[object_name]

        def remove_object(self, object_name):  # noqa: ANN001
            store.pop(object_name, None)

    monkeypatch.setattr(minio_module, "get_minio_client", lambda settings=None: FakeMinio())

    headers = _auth_headers(superuser_token)

    def png(color):  # noqa: ANN001
        buf = BytesIO()
        Image.new("RGB", (16, 16), color=color).save(buf, format="PNG")
        return buf.getvalue()

    # Logo principal oscuro → logo_is_dark True
    up = await client.post(
        "/api/v1/configuration/email/logo",
        headers=headers,
        files={"file": ("l.png", png((10, 10, 10)), "image/png")},
    )
    assert up.status_code == 200, up.text
    b = await client.get("/api/v1/configuration/branding", headers=headers)
    assert b.json()["has_custom_logo"] is True
    assert b.json()["logo_is_dark"] is True

    # Logo para fondos oscuros
    upd = await client.post(
        "/api/v1/configuration/email/logo/dark",
        headers=headers,
        files={"file": ("d.png", png((240, 240, 240)), "image/png")},
    )
    assert upd.status_code == 200, upd.text
    b2 = await client.get("/api/v1/configuration/branding", headers=headers)
    assert b2.json()["has_dark_logo"] is True

    served = await client.get("/api/v1/configuration/branding/logo/dark", headers=headers)
    assert served.status_code == 200
    assert served.content.startswith(b"\x89PNG")

    # Superficie configurable
    put = await client.put(
        "/api/v1/configuration/organization",
        headers=headers,
        json={"logo_surface": "light"},
    )
    assert put.status_code == 200, put.text
    assert put.json()["logo_surface"] == "light"

    # Quitar logo oscuro
    dele = await client.delete("/api/v1/configuration/email/logo/dark", headers=headers)
    assert dele.status_code == 200
    b3 = await client.get("/api/v1/configuration/branding", headers=headers)
    assert b3.json()["has_dark_logo"] is False