"""Wholesale authentication: signup request, login, session, and logout."""

from sanic import Blueprint
from sanic.response import json
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from ..auth import (
    COOKIE_NAME,
    SESSION_MAX_AGE,
    create_session_token,
    get_current_user,
    hash_password,
    revoke_session,
    user_payload,
    verify_login_password,
)
from ..db import session_scope
from ..models import FloristProfile, User
from ..security import audit, password_error, queue_mail, throttle, valid_email, verify_mfa
from ..settings import get_settings

bp = Blueprint("auth", url_prefix="/api/auth")


def _set_session(response, token: str, max_age: int = SESSION_MAX_AGE) -> None:
    response.add_cookie(
        COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        samesite="Lax",
        secure=not get_settings().debug,
    )


@bp.get("/me/")
async def me(request):
    """Return the current wholesale account payload."""
    return json(user_payload(await get_current_user(request)))


@bp.post("/signup/")
async def signup(request):
    """Request a wholesale florist account for operator approval."""
    data = request.json or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    business = str(data.get("business_name", "")).strip()
    contact_name = str(data.get("name", "")).strip()
    business_type = str(data.get("business_type", "")).strip()
    website = str(data.get("website", "")).strip()
    about_work = str(data.get("message", "")).strip()

    if not email or not password or not business or not contact_name:
        return json({"detail": "Name, business name, email, and password are required."}, status=400)
    if not valid_email(email) or password_error(password):
        return json({"detail": password_error(password) or "Enter a valid email."}, status=400)
    if not await throttle(request, "signup", email, limit=5):
        return json({"detail": "Please try again later."}, status=429)
    if business_type and business_type not in {"florist", "event", "shop", "other"}:
        return json({"detail": "Select a valid business type."}, status=400)
    if website and not website.startswith("https://"):
        return json({"detail": "Use an HTTPS website URL."}, status=400)
    phone = str(data.get("phone", "")).strip()
    if (
        len(contact_name) > 200
        or len(business) > 200
        or len(phone) > 40
        or len(website) > 500
        or len(about_work) > 5000
    ):
        return json({"detail": "Some account details are too long."}, status=400)

    async with session_scope() as session:
        password_hash = hash_password(password)
        if await session.scalar(select(User).where(User.email == email)):
            return json({"detail": "Request received. If eligible, Isabella will review your account."}, status=201)
        user = User(email=email, password_hash=password_hash, is_active=True)
        session.add(
            FloristProfile(
                business_name=business,
                contact_name=contact_name,
                phone=phone,
                business_type=business_type,
                website=website,
                about_work=about_work,
                approved=False,
                user=user,
            )
        )
        queue_mail(
            session,
            email,
            "Application received",
            "Your wholesale application is awaiting owner review. Approval and account activation are separate.",
        )
        queue_mail(
            session,
            get_settings().inquiry_notification_email,
            "Wholesale application",
            f"Review the application from {business} in Account security.",
        )
        try:
            await session.flush()
            audit(session, request, "signup", target=user.id)
            await session.commit()
        except IntegrityError:
            # Concurrent duplicate registration preserves the generic response.
            await session.rollback()

    return json(
        {"detail": "Request received. If eligible, Isabella will review your account."},
        status=201,
    )


@bp.post("/login/")
async def login(request):
    """Validate credentials and start a signed session cookie."""
    data = request.json or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    if not await throttle(request, "login", email):
        return json({"detail": "Invalid credentials or too many attempts. Try again later."}, status=429)

    async with session_scope() as session:
        result = await session.execute(
            select(User).options(selectinload(User.profile)).where(User.email == email).with_for_update()
        )
        user = result.scalar_one_or_none()
        valid = verify_login_password(user, password)
        if not valid or user.role != "florist":
            audit(session, request, "login", target=user.id if user else None, outcome="failed")
            await session.commit()
            return json({"detail": "Invalid email or password."}, status=400)
        if user.mfa_secret and not verify_mfa(user, str(data.get("mfa_code", ""))):
            audit(session, request, "login_mfa", target=user.id, outcome="failed")
            await session.commit()
            return json({"detail": "Enter a valid authenticator or recovery code."}, status=400)
        audit(session, request, "login", actor=user.id, target=user.id)
        payload = user_payload(user)
        user_id = user.id
        version = user.security_version
        await session.commit()

    response = json(payload)
    _set_session(response, await create_session_token(user_id, expected_version=version))
    return response


@bp.post("/logout/")
async def logout(request):
    """Clear the wholesale session cookie."""
    response = json({"authenticated": False})
    user = await get_current_user(request)
    async with session_scope() as db:
        audit(db, request, "logout", actor=user.id if user else None, target=user.id if user else None)
        await db.commit()
    await revoke_session(request.cookies.get(COOKIE_NAME, ""))
    _set_session(response, "", max_age=0)
    return response
