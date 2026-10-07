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

import pytest_asyncio  # noqa: E402

from app import models  # noqa: E402,F401
from app.db import Base, get_engine  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def _schema():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
