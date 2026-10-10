"""Sanic application factory for the Honey Summer API.

The admin at ``/admin`` and the JSON API share this single app/port.
"""

from sanic import Sanic
from sanic.response import json
from sanic_ext import Extend

from .admin import bp as admin_bp
from .request_security import protect_request, secure_response
from .routes.auth import bp as auth_bp
from .routes.catalog import bp as catalog_bp
from .routes.checkout import bp as checkout_bp
from .routes.content import bp as content_bp
from .routes.inquiries import bp as inquiries_bp
from .routes.retail import bp as retail_bp
from .security import cipher, public_link
from .security_views import bp as security_bp
from .settings import get_settings

settings = get_settings()
if not settings.debug:
    if len(settings.secret_key) < 32 or settings.secret_key == "insecure-local-development-key":
        raise RuntimeError("Production SECRET_KEY must be a unique high-entropy secret of at least 32 characters.")
    cipher()  # Fail closed instead of discovering missing MFA keys at first login.
    public_link("")

app = Sanic("honey-summer")
app.config.SECRET = settings.secret_key
app.config.CORS = False
app.config.ACCESS_LOG = False  # Recovery query strings must never enter access logs.
Extend(app)
app.register_middleware(protect_request, "request")
app.register_middleware(secure_response, "response")
# The interactive API docs are a development convenience only.
app.config.OAS = settings.debug

settings.media_root.mkdir(parents=True, exist_ok=True)
app.static("/media", str(settings.media_root), index="index.html")

app.blueprint(admin_bp)
app.blueprint(auth_bp)
app.blueprint(catalog_bp)
app.blueprint(checkout_bp)
app.blueprint(content_bp)
app.blueprint(inquiries_bp)
app.blueprint(retail_bp)
app.blueprint(security_bp)


@app.get("/api/health/")
async def health(request):
    """Return API liveness status for health checks."""
    return json({"status": "ok", "service": "honey-summer-api"})
