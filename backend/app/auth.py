"""Cookie sessions and password hashing.

Sessions are signed, HTTP-only cookies holding only the user id (stateless, so
they work across workers); passwords are hashed with Argon2.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .db import session_scope
from .models import User
from .settings import get_settings

COOKIE_NAME = "honeysummer_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

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


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="honey-summer-session")


def create_session_token(user_id: int) -> str:
    """Sign a session token holding only the user id."""
    return _serializer().dumps({"uid": user_id})


def read_session_token(token: str) -> int | None:
    """Return the user id from a valid, unexpired session token."""
    try:
        data = _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except BadSignature, SignatureExpired:
        return None
    uid = data.get("uid") if isinstance(data, dict) else None
    return uid if isinstance(uid, int) else None


async def get_current_user(request) -> User | None:
    """Load the signed-in user from the request cookie, if any."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    uid = read_session_token(token)
    if uid is None:
        return None
    async with session_scope() as session:
        result = await session.execute(select(User).options(selectinload(User.profile)).where(User.id == uid))
        user = result.scalar_one_or_none()
        return user if user and user.is_active else None


def user_payload(user: User | None) -> dict:
    """Build the public authentication payload for a user."""
    profile = user.profile if user else None
    return {
        "authenticated": bool(user),
        "id": user.id if user else None,
        "approved": bool(profile and profile.approved),
        "business_name": profile.business_name if profile else "",
    }
