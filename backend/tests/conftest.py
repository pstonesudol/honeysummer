"""Test bootstrap for the Sanic suite.

A throwaway SQLite database is configured before the app is imported so the
lazy engine never touches the development Postgres instance. The schema is
created and dropped around every test.
"""

import os
import tempfile

_fd, _path = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_path}"
os.environ.setdefault("RESEND_API_KEY", "")
# Force debug mode so session and CSRF cookies are issued without the Secure
# flag. The Sanic test client speaks plain HTTP and httpx refuses to send
# Secure cookies over it, which silently breaks login and CSRF. We set this
# explicitly instead of relying on backend/.env, which is gitignored and so
# absent in CI.
os.environ["DEBUG"] = "true"

import pyotp  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app import models  # noqa: E402,F401
from app.db import (  # noqa: E402
    Base,
    get_engine,
    session_scope,  # noqa: E402
)
from app.models import User  # noqa: E402
from app.security import decrypt  # noqa: E402
from app.security_views import CSRF_COOKIE as SECURITY_CSRF_COOKIE  # noqa: E402
from app.server import app as sanic_app  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def _schema():
    sanic_app.asgi_client.cookies.clear()
    sanic_app.asgi_client.headers["X-HoneySummer-Request"] = "1"
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    sanic_app.asgi_client.cookies.clear()


@pytest_asyncio.fixture(autouse=True)
async def _complete_legacy_operator_login(request, monkeypatch):
    """Operations tests sign operators in directly; complete MFA only when one is enrolled.

    Security tests drive both steps themselves to exercise the preauth boundary.
    """
    if request.node.path.name == "test_security.py":
        return
    original = sanic_app.asgi_client.post

    async def post(url, *args, **kwargs):
        result = await original(url, *args, **kwargs)
        response = result[1]
        if url == "/admin/login" and response.status == 302:
            location = response.headers.get("location", "")
            if location.endswith("/admin/security/mfa"):
                await sanic_app.asgi_client.get("/admin/security/mfa")
                async with session_scope() as db:
                    email = kwargs.get("data", {}).get("email", "")
                    user = await db.scalar(select(User).where(User.email == email))
                    secret = decrypt(user.mfa_secret or user.mfa_pending)
                csrf = sanic_app.asgi_client.cookies.get(SECURITY_CSRF_COOKIE)
                _, mfa = await original(
                    "/admin/security/mfa", data={"csrf_token": csrf, "code": pyotp.TOTP(secret).now()}
                )
                assert mfa.status in {200, 302}, mfa.text
        return result

    monkeypatch.setattr(sanic_app.asgi_client, "post", post)
