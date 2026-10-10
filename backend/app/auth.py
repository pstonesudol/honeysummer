"""Argon2 passwords and database-backed opaque, revocable sessions."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from .db import session_scope
from .models import User
from .security_models import AccountSession

COOKIE_NAME = "honeysummer_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 14  # 14-day absolute florist lifetime

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a plaintext password with Argon2."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Check a plaintext password against its stored Argon2 hash."""
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError, VerificationError, InvalidHashError:
        return False


_dummy_password_hash = hash_password(secrets.token_urlsafe(32))


def verify_login_password(user: User | None, password: str) -> bool:
    """Unknown/inactive addresses still pay the normal Argon2 verification cost."""
    if len(password) > 1024:
        return False
    verified = verify_password(user.password_hash if user else _dummy_password_hash, password)
    return bool(user and user.is_active and verified)


def token_digest(token: str) -> str:
    """Hash high-entropy session/challenge material before storing it."""
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session_token(user_id: int, scope: str = "florist", *, expected_version: int | None = None) -> str:
    """Create a fresh registry entry; legacy signed cookies are not accepted."""
    token = secrets.token_urlsafe(32)
    async with session_scope() as db:
        user = await db.get(User, user_id)
        if (
            not user
            or not user.is_active
            or (expected_version is not None and user.security_version != expected_version)
        ):
            raise ValueError("Inactive account.")
        db.add(
            AccountSession(
                token_hash=token_digest(token),
                user_id=user_id,
                version=user.security_version,
                scope=scope,
                expires_at=datetime.now(UTC) + timedelta(hours=12 if scope == "admin" else 24 * 14),
            )
        )
        await db.commit()
        return token


def aware(value: datetime) -> datetime:
    """SQLite test timestamps and Postgres timestamps share UTC semantics."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


async def revoke_session(token: str) -> None:
    """Invalidate a browser cookie on the server, including copied cookies."""
    async with session_scope() as db:
        await db.execute(delete(AccountSession).where(AccountSession.token_hash == token_digest(token)))
        await db.commit()


async def session_user(request, cookie: str, scope: str) -> User | None:
    """Recheck activation, version, expiry and scope on every request."""
    token = request.cookies.get(cookie, "")
    if not token or len(token) > 100:
        return None
    now = datetime.now(UTC)
    async with session_scope() as db:
        row = await db.get(AccountSession, token_digest(token))
        if not row or row.scope != scope or aware(row.expires_at) <= now:
            return None
        idle = timedelta(minutes=30) if scope == "admin" else timedelta(days=3)
        if aware(row.last_seen_at) + idle <= now:
            return None
        user = await db.scalar(select(User).options(selectinload(User.profile)).where(User.id == row.user_id))
        if not user or not user.is_active or user.security_version != row.version:
            return None
        row.last_seen_at = now
        request.ctx.account_session = row
        await db.commit()
        return user


async def get_current_user(request) -> User | None:
    """Load the signed-in user from the request cookie, if any."""
    user = await session_user(request, COOKIE_NAME, "florist")
    return user if user and user.role == "florist" else None


def user_payload(user: User | None) -> dict:
    """Build the public authentication payload for a user."""
    profile = user.profile if user else None
    return {
        "authenticated": bool(user),
        "id": user.id if user else None,
        "approved": bool(profile and profile.approved),
        "business_name": profile.business_name if profile else "",
    }
