"""Opt-in staging origin authentication, independent of account/CSRF controls."""

import re
import secrets

from sanic.response import json

from .settings import get_settings

STAGING_ORIGIN = "https://staging.hellohoneysummer.com"
ORIGIN_HEADER = "x-honeysummer-origin-secret"


def validate_origin_gate(settings):
    """Fail startup for an enabled gate with unsafe scope or missing credentials."""
    if not settings.staging_origin_gate_enabled:
        return
    if settings.public_origin != STAGING_ORIGIN or settings.debug:
        raise RuntimeError("Origin gate may only be enabled for non-debug staging.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", settings.staging_origin_secret.get_secret_value()):
        raise RuntimeError("Staging origin gate requires a 43–128 character URL-safe random secret.")


async def protect_origin(request):
    """Reject direct requests before account middleware; leave only narrow exceptions."""
    settings = get_settings()
    if not settings.staging_origin_gate_enabled:
        return
    # Exact paths/methods, never prefix matches or header-presence exemptions.
    if request.path == "/api/health/" and request.method in {"GET", "HEAD"}:
        return
    if (
        request.path == "/api/stripe/webhook/"
        and request.method == "POST"
        and settings.stripe_secret_key.startswith("sk_test_")
        and settings.stripe_webhook_secret.startswith("whsec_")
    ):
        return  # Handler still verifies Stripe's signature/body before dispatching.
    values = request.headers.getall(ORIGIN_HEADER, [])
    expected = settings.staging_origin_secret.get_secret_value()
    if len(values) == 1 and expected and secrets.compare_digest(values[0].encode(), expected.encode()):
        return
    return json({"detail": "Origin access denied."}, status=403, headers={"Cache-Control": "no-store"})
