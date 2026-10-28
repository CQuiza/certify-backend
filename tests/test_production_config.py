"""Guardrails de configuración de producción."""

from types import SimpleNamespace

import pytest

import app.main as main


def _settings(**overrides):
    values = {
        "environment": "production",
        "superuser_password": "ProdPassw0rd!123",
        "secret_key": "x" * 64,
        "base_url": "https://app.example.com",
        "cors_origins": ["https://app.example.com"],
        "allowed_hosts": ["app.example.com"],
        "payments_enabled": False,
        "mercadopago_webhook_secret": "",
        "turnstile_secret_key": "turnstile-secret",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_production_rejects_default_superuser_password(monkeypatch):
    monkeypatch.setattr(main, "get_settings", lambda: _settings(superuser_password="Ch4ng3M3!"))
    with pytest.raises(RuntimeError, match="SUPERUSER_PASSWORD"):
        main._validate_production_settings()


def test_production_rejects_localhost_cors_and_hosts(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: _settings(
            cors_origins=["http://localhost:3000"],
            allowed_hosts=["localhost"],
        ),
    )
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        main._validate_production_settings()


def test_production_accepts_complete_config(monkeypatch):
    monkeypatch.setattr(main, "get_settings", lambda: _settings())
    main._validate_production_settings()


def test_production_rejects_missing_turnstile_secret(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: _settings(turnstile_secret_key=""),
    )
    with pytest.raises(RuntimeError, match="TURNSTILE_SECRET_KEY"):
        main._validate_production_settings()
