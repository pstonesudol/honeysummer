"""Wholesale authentication: signup request, login, session, and logout."""

from sanic import Blueprint
from sanic.response import json
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..auth import (
    COOKIE_NAME,
    SESSION_MAX_AGE,
    create_session_token,
    get_current_user,
    hash_password,
    user_payload,
    verify_password,
)
from ..db import session_scope
from ..emails import send_signup_notification
from ..models import FloristProfile, User
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
    return json(user_payload(await get_current_user(request)))


@bp.post("/signup/")
async def signup(request):
    data = request.json or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    business = str(data.get("business_name", "")).strip()
    contact_name = str(data.get("name", "")).strip()
    business_type = str(data.get("business_type", "")).strip()
    website = str(data.get("website", "")).strip()
    about_work = str(data.get("message", "")).strip()

    if not email or not password or not business or not contact_name:
        return json(
            {"detail": "Name, business name, email, and password are required."}, status=400
        )
    if business_type and business_type not in {"florist", "event", "shop", "other"}:
        return json({"detail": "Select a valid business type."}, status=400)
    phone = str(data.get("phone", "")).strip()
    if len(contact_name) > 200 or len(business) > 200 or len(phone) > 40 or len(website) > 500 or len(about_work) > 5000:
        return json({"detail": "Some account details are too long."}, status=400)

    async with session_scope() as session:
        if await session.scalar(select(User).where(User.email == email)):
            return json(
                {"detail": "An account with this email already exists."}, status=400
            )
        user = User(email=email, password_hash=hash_password(password), is_active=True)
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
        await session.commit()

    send_signup_notification(business_name=business, email=email, contact_name=contact_name)
    return json(
        {"detail": "Request received. Isabella will approve your account shortly."},
        status=201,
    )


@bp.post("/login/")
async def login(request):
    data = request.json or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    async with session_scope() as session:
        result = await session.execute(
            select(User).options(selectinload(User.profile)).where(User.email == email)
        )
        user = result.scalar_one_or_none()
        if not user or not user.is_active or not verify_password(user.password_hash, password):
            return json({"detail": "Invalid email or password."}, status=400)
        payload = user_payload(user)
        user_id = user.id

    response = json(payload)
    _set_session(response, create_session_token(user_id))
    return response


@bp.post("/logout/")
async def logout(request):
    response = json({"authenticated": False})
    _set_session(response, "", max_age=0)
    return response
