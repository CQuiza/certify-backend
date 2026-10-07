"""Pruebas del servicio de configuración de plataforma (SQLite)."""

import pytest

from app.core.crypto import decrypt_secret, password_is_set
from app.models.platform_settings import PlatformSettings
from app.repositories.platform_settings_repository import platform_settings_repository
from app.services.platform_settings_service import platform_settings_service


@pytest.mark.asyncio
async def test_get_or_create_singleton(db):
    row1 = await platform_settings_service.get_or_create(db)
    row2 = await platform_settings_service.get_or_create(db)
    assert row1.id == row2.id
    assert isinstance(row1, PlatformSettings)


@pytest.mark.asyncio
async def test_branding_defaults(db):
    branding = await platform_settings_service.get_branding(db)
    assert branding["dashboard_message"] == (
        "Panel principal de la plataforma Certify para la organización Certify"
    )
    assert branding["organization_name"] is None
    assert branding["has_custom_logo"] is False


@pytest.mark.asyncio
async def test_save_organization_updates_branding(db):
    await platform_settings_service.save_organization(
        db, organization_name="ACME", dashboard_message=None, updated_by=1
    )
    branding = await platform_settings_service.get_branding(db)
    assert branding["organization_name"] == "ACME"
    assert "ACME" in branding["dashboard_message"]


@pytest.mark.asyncio
async def test_custom_dashboard_message(db):
    await platform_settings_service.save_organization(
        db,
        organization_name="Globex",
        dashboard_message="Bienvenidos a {{app_name}} — {{organization}}",
        updated_by=1,
    )
    branding = await platform_settings_service.get_branding(db)
    assert branding["dashboard_message"] == "Bienvenidos a Certify — Globex"


@pytest.mark.asyncio
async def test_email_password_encrypted_and_never_returned(db):
    await platform_settings_service.save_email_settings(
        db,
        smtp_enabled=True,
        smtp_host="smtp.acme.com",
        smtp_port=587,
        smtp_user="soporte@acme.com",
        smtp_password="S3cret!",
        clear_smtp_password=False,
        smtp_tls=True,
        email_from="noreply@acme.com",
        email_from_name="ACME",
        updated_by=1,
    )
    view = await platform_settings_service.get_email_settings(db)
    assert view["smtp_password_set"] is True
    assert view["smtp_host"] == "smtp.acme.com"
    assert "password" not in view or view.get("smtp_password") is None

    row = await platform_settings_service.get_or_create(db)
    assert password_is_set(row.smtp_password_encrypted)
    assert decrypt_secret(row.smtp_password_encrypted) == "S3cret!"


@pytest.mark.asyncio
async def test_email_password_clear(db):
    await platform_settings_service.save_email_settings(
        db,
        smtp_enabled=True,
        smtp_host="smtp.acme.com",
        smtp_port=587,
        smtp_user="u",
        smtp_password="S3cret!",
        clear_smtp_password=False,
        smtp_tls=True,
        email_from=None,
        email_from_name=None,
        updated_by=1,
    )
    await platform_settings_service.save_email_settings(
        db,
        smtp_enabled=True,
        smtp_host="smtp.acme.com",
        smtp_port=587,
        smtp_user="u",
        smtp_password=None,
        clear_smtp_password=True,
        smtp_tls=True,
        email_from=None,
        email_from_name=None,
        updated_by=1,
    )
    view = await platform_settings_service.get_email_settings(db)
    assert view["smtp_password_set"] is False


@pytest.mark.asyncio
async def test_resolve_email_config_prefers_db(db):
    await platform_settings_service.save_email_settings(
        db,
        smtp_enabled=True,
        smtp_host="smtp.db.com",
        smtp_port=2525,
        smtp_user="db-user",
        smtp_password="db-pass",
        clear_smtp_password=False,
        smtp_tls=False,
        email_from="db@db.com",
        email_from_name="DB",
        updated_by=1,
    )
    cfg = await platform_settings_service.resolve_email_config(db)
    assert cfg is not None
    assert cfg.host == "smtp.db.com"
    assert cfg.port == 2525
    assert cfg.user == "db-user"
    assert cfg.password == "db-pass"
    assert cfg.from_email == "db@db.com"


@pytest.mark.asyncio
async def test_email_templates_defaults_then_custom_then_restore(db):
    row = await platform_settings_service.get_or_create(db)

    default = await platform_settings_service.get_email_template(db, "credentials")
    assert default["is_custom"] is False
    assert "credenciales" in default["subject"]

    custom = await platform_settings_service.save_email_template(
        db,
        kind="credentials",
        subject="Hola {{app_name}} custom",
        body_html="<p>Custom body</p>",
        is_enabled=True,
        updated_by=1,
    )
    assert custom["is_custom"] is True
    assert custom["subject"] == "Hola {{app_name}} custom"

    restored = await platform_settings_service.restore_email_template(
        db, "credentials", updated_by=1
    )
    assert restored["is_custom"] is False


@pytest.mark.asyncio
async def test_email_template_disabled_falls_back_to_default(db):
    row = await platform_settings_service.get_or_create(db)
    await platform_settings_service.save_email_template(
        db,
        kind="certificate_issued",
        subject="Custom subject",
        body_html="<p>x</p>",
        is_enabled=False,
        updated_by=1,
    )
    t = await platform_settings_service.get_email_template(db, "certificate_issued")
    assert t["is_custom"] is False


@pytest.mark.asyncio
async def test_repository_update_allows_keys(db):
    row = await platform_settings_service.get_or_create(db)
    updated = await platform_settings_repository.update(
        db, row, {"organization_name": "ACME", "not_allowed": "x"}
    )
    assert updated.organization_name == "ACME"
    assert not hasattr(updated, "not_allowed")