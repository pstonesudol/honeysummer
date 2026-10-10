"""Same-origin mutation policy, independent of untrusted proxy Host headers."""

from sanic.response import json

from .db import session_scope
from .security import audit
from .settings import get_settings


async def _rejected(request, detail: str):
    async with session_scope() as db:
        audit(db, request, "request_rejected", outcome="blocked")
        await db.commit()
    return json({"detail": detail}, status=403)


async def protect_request(request):
    """Custom-header CSRF for JSON APIs; form CSRF remains enforced by each UI."""
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    if request.path.rstrip("/") == "/api/stripe/webhook":
        return  # Signed Stripe events are not browser-cookie authentication.
    if not (request.path.startswith("/api/") or request.path.startswith("/admin")):
        return
    origin = request.headers.get("origin")
    expected = get_settings().public_origin.rstrip("/")
    if origin and origin != expected:
        detail = "Cross-origin mutation rejected."
        if get_settings().debug:
            detail += f" Received {origin!r}; expected {expected!r}."
        return await _rejected(request, detail)
    if request.path.startswith("/admin") and not get_settings().debug and origin != expected:
        return await _rejected(request, "Same-origin form submission required.")
    if request.headers.get("sec-fetch-site") == "cross-site":
        return await _rejected(request, "Cross-site mutation rejected.")
    if request.path.startswith("/api/") and request.path.rstrip("/") != "/api/inquiries":
        if request.headers.get("x-honeysummer-request") != "1":
            return await _rejected(request, "CSRF request header required.")


async def secure_response(request, response):
    """Auth responses are never cacheable and cannot be framed."""
    if request.path.startswith(("/admin", "/api/auth", "/api/cart")):
        if "no-store" not in response.headers.get("Cache-Control", ""):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        # Chrome form POSTs under no-referrer can send Origin:null. Keep Origin
        # checks usable while never forwarding a recovery URL's path/query.
        response.headers["Referrer-Policy"] = "strict-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"
