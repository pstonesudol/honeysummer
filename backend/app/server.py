"""Sanic application factory for the Honey Summer API.

The admin at ``/admin`` and the JSON API share this single app/port.
"""

from sanic import Sanic
from sanic.response import json
from sanic_ext import Extend

from .admin import bp as admin_bp
from .routes.auth import bp as auth_bp
from .routes.catalog import bp as catalog_bp
from .routes.checkout import bp as checkout_bp
from .routes.content import bp as content_bp
from .routes.inquiries import bp as inquiries_bp
from .settings import get_settings

app = Sanic("honey-summer")
app.config.SECRET = get_settings().secret_key
Extend(app)

app.blueprint(admin_bp)
app.blueprint(auth_bp)
app.blueprint(catalog_bp)
app.blueprint(checkout_bp)
app.blueprint(content_bp)
app.blueprint(inquiries_bp)


@app.get("/api/health/")
async def health(request):
    return json({"status": "ok", "service": "honey-summer-api"})
