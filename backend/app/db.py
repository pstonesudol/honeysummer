"""Async SQLAlchemy engine and session.

The Sanic app owns its schema from scratch (no reuse of Django's tables), so
the engine is created lazily to let tests point at a throwaway database.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .settings import get_settings


class Base(DeclarativeBase):
    """Declarative base shared by all Sanic models."""


def to_async_url(url: str) -> str:
    """Convert a PostgreSQL URL to its asyncpg driver form."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the lazily-created async engine shared by the app."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(to_async_url(get_settings().database_url), pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the lazily-created async session factory."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Yield an async session to the caller's context."""
    async with get_sessionmaker()() as session:
        yield session
