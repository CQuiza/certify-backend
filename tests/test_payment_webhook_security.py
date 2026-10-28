"""Firma e idempotencia del webhook de Mercado Pago."""

import hashlib
import hmac
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.services import payment_service


def _request(headers: dict[str, str], data_id: str) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/payments/webhook",
        "query_string": f"data.id={data_id}".encode(),
        "headers": [
            (key.lower().encode(), value.encode()) for key, value in headers.items()
        ],
    }
    return Request(scope)


def _signature(secret: str, data_id: str, request_id: str, ts: str) -> str:
    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    digest = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return f"ts={ts},v1={digest}"


def test_webhook_signature_accepts_valid_and_rejects_invalid(monkeypatch):
    secret = "webhook-secret"
    data_id = "12345"
    request_id = "req-1"
    ts = "1700000000"
    headers = {
        "x-signature": _signature(secret, data_id, request_id, ts),
        "x-request-id": request_id,
    }

    monkeypatch.setattr(
        payment_service,
        "get_settings",
        lambda: SimpleNamespace(
            mercadopago_webhook_secret=secret,
            environment="production",
        ),
    )

    assert payment_service.verify_webhook_signature(_request(headers, data_id), data_id)

    headers["x-signature"] = "ts=bad,v1=bad"
    assert not payment_service.verify_webhook_signature(_request(headers, data_id), data_id)


def test_webhook_signature_fails_closed_without_secret_in_production(monkeypatch):
    monkeypatch.setattr(
        payment_service,
        "get_settings",
        lambda: SimpleNamespace(
            mercadopago_webhook_secret="",
            environment="production",
        ),
    )
    request = _request({}, "123")
    assert not payment_service.verify_webhook_signature(request, "123")
