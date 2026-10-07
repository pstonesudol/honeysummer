"""Sanic application factory for the Honey Summer API.

The admin at ``/admin`` and the JSON API share this single app/port.
"""

from sanic import Sanic
from sanic.response import json
from sanic_ext import Extend

from .routes.content import bp as content_bp
from .routes.inquiries import bp as inquiries_bp
from .settings import get_settings

app = Sanic("honey-summer")
app.config.SECRET = get_settings().secret_key
Extend(app)

app.blueprint(content_bp)
app.blueprint(inquiries_bp)


@app.get("/api/health/")
async def health(request):
    return json({"status": "ok", "service": "honey-summer-api"})
