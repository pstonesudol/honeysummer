"""Direct-origin denial and narrow exception regression tests."""

import hashlib
import hmac
import time
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from app.origin_gate import ORIGIN_HEADER, STAGING_ORIGIN, validate_origin_gate
from app.routes import checkout
from app.server import app
from app.settings import Settings, get_settings

SECRET = "synthetic_" + "a" * 43


@pytest.fixture
def gated(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "staging_origin_gate_enabled", True)
    monkeypatch.setattr(settings, "staging_origin_secret", SecretStr(SECRET))
    monkeypatch.setattr(settings, "public_origin", STAGING_ORIGIN)
    return settings


@pytest.mark.parametrize("path", ["/admin/login", "/admin/", "/api/retail/flowers/", "/media/missing.jpg", "/"])
async def test_direct_origin_denies_routes_before_auth(gated, path):
    _, response = await app.asgi_client.get(path)
    assert response.status == 403
    assert response.json == {"detail": "Origin access denied."}
    assert response.headers["cache-control"] == "no-store"
    assert SECRET not in response.text


async def test_secret_allows_routing_but_does_not_grant_admin(gated):
    _, response = await app.asgi_client.get("/api/retail/flowers/", headers={ORIGIN_HEADER: SECRET})
    assert response.status == 200
    _, response = await app.asgi_client.get("/admin/", headers={ORIGIN_HEADER: SECRET}, follow_redirects=False)
    assert response.status == 302
    assert response.headers["location"] == "/admin/login"


@pytest.mark.parametrize("value", ["wrong", "", SECRET + ",wrong"])
async def test_bad_secret_is_denied(gated, value):
    _, response = await app.asgi_client.get("/admin/login", headers={ORIGIN_HEADER: value})
    assert response.status == 403


async def test_health_exception_is_exact_and_read_only(gated):
    _, response = await app.asgi_client.get("/api/health/")
    assert response.status == 200
    for path in ["/api/health", "/api/health/other"]:
        _, response = await app.asgi_client.get(path, follow_redirects=False)
        assert response.status == 403
    _, response = await app.asgi_client.post("/api/health/")
    assert response.status == 403


async def test_webhook_is_closed_until_sandbox_configured_and_still_checks_signature(gated, monkeypatch):
    monkeypatch.setattr(gated, "stripe_secret_key", "")
    monkeypatch.setattr(gated, "stripe_webhook_secret", "")
    _, response = await app.asgi_client.post("/api/stripe/webhook/", json={})
    assert response.status == 403
    monkeypatch.setattr(gated, "stripe_secret_key", "sk_test_synthetic")
    monkeypatch.setattr(gated, "stripe_webhook_secret", "whsec_synthetic")
    _, response = await app.asgi_client.post("/api/stripe/webhook/", json={})
    assert response.status == 400
    for path in ["/api/stripe/webhook", "/api/stripe/webhook/other", "/api/retail/flowers/"]:
        _, response = await app.asgi_client.post(path, json={}, headers={"Stripe-Signature": "synthetic"})
        assert response.status == 403
    monkeypatch.setattr(gated, "stripe_secret_key", "sk_live_synthetic")
    _, response = await app.asgi_client.post("/api/stripe/webhook/", json={})
    assert response.status == 403


async def test_origin_secret_does_not_bypass_csrf(gated):
    _, response = await app.asgi_client.post("/admin/login", data={}, headers={ORIGIN_HEADER: SECRET})
    assert response.status == 403
    assert "Origin access denied" not in response.text


async def test_valid_sandbox_webhook_reaches_signature_checked_dispatch(gated, monkeypatch):
    monkeypatch.setattr(gated, "stripe_secret_key", "sk_test_synthetic")
    monkeypatch.setattr(gated, "stripe_webhook_secret", "whsec_synthetic")
    dispatch = AsyncMock(return_value="applied")
    monkeypatch.setattr(checkout, "apply_checkout_event", dispatch)
    body = '{"id":"evt_synthetic","type":"synthetic.event","data":{"object":{}}}'
    timestamp = int(time.time())
    signature = hmac.new(b"whsec_synthetic", f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()
    _, response = await app.asgi_client.post(
        "/api/stripe/webhook/",
        content=body,
        headers={"Stripe-Signature": f"t={timestamp},v1={signature}", "Content-Type": "application/json"},
    )
    assert response.status == 200
    dispatch.assert_awaited_once()


def test_enabled_gate_requires_non_debug_staging_and_valid_secret():
    base = dict(
        _env_file=None,
        public_origin=STAGING_ORIGIN,
        debug=False,
        staging_origin_gate_enabled=True,
        staging_origin_secret=SECRET,
    )
    validate_origin_gate(Settings(**base))
    for changes in [
        dict(debug=True),
        dict(public_origin="https://hellohoneysummer.com"),
        dict(staging_origin_secret=""),
        dict(staging_origin_secret="short"),
    ]:
        with pytest.raises(RuntimeError):
            validate_origin_gate(Settings(**(base | changes)))
    assert SECRET not in repr(Settings(**base))
    validate_origin_gate(Settings(_env_file=None, staging_origin_gate_enabled=False))
