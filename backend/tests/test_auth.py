import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import emails
from app.auth import hash_password
from app.db import session_scope
from app.models import FloristProfile, User
from app.server import app


@pytest.fixture
def sent(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(emails, "send_email", lambda **kwargs: calls.append(kwargs))
    return calls


async def _make_user(
    email: str = "florist@example.com",
    password: str = "flowers-are-nice",
    approved: bool = True,
) -> None:
    async with session_scope() as session:
        user = User(email=email, password_hash=hash_password(password), is_active=True)
        session.add(
            FloristProfile(business_name="Fern & Fig", approved=approved, user=user)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_signup_creates_unapproved_profile_and_notifies_the_farm(sent):
    _, response = await app.asgi_client.post(
        "/api/auth/signup/",
        json={
            "business_name": "Fern & Fig",
            "name": "Jamie Rivera",
            "email": "New@Example.com",
            "password": "flowers-are-nice",
            "phone": "570-555-0100",
            "business_type": "florist",
            "website": "https://example.com",
            "message": "Seasonal wedding designs",
        },
    )

    assert response.status == 201
    async with session_scope() as session:
        result = await session.execute(select(User).options(selectinload(User.profile)))
        user = result.scalar_one()
    assert user.email == "new@example.com"
    assert user.profile.approved is False
    assert user.profile.business_name == "Fern & Fig"
    assert user.profile.contact_name == "Jamie Rivera"
    assert user.profile.business_type == "florist"
    assert user.profile.website == "https://example.com"
    assert user.profile.about_work == "Seasonal wedding designs"
    assert len(sent) == 1
    assert sent[0]["to"] == "hello@hellohoneysummer.com"
    assert "new@example.com" in sent[0]["body"]
    assert "Jamie Rivera" in sent[0]["body"]


@pytest.mark.asyncio
async def test_signup_rejects_a_duplicate_email(sent):
    await _make_user()

    _, response = await app.asgi_client.post(
        "/api/auth/signup/",
        json={"name": "Jamie", "business_name": "X", "email": "florist@example.com", "password": "flowers-are-nice"},
    )

    assert response.status == 400


@pytest.mark.asyncio
async def test_signup_requires_business_email_and_password(sent):
    _, response = await app.asgi_client.post(
        "/api/auth/signup/", json={"email": "someone@example.com"}
    )

    assert response.status == 400
    async with session_scope() as session:
        assert (await session.scalar(select(User))) is None


@pytest.mark.asyncio
async def test_signup_requires_contact_name_and_rejects_unknown_business_type(sent):
    details = {"business_name": "Fern & Fig", "email": "new@example.com", "password": "flowers-are-nice"}
    _, missing_name = await app.asgi_client.post("/api/auth/signup/", json=details)
    _, invalid_type = await app.asgi_client.post(
        "/api/auth/signup/", json={**details, "name": "Jamie", "business_type": "unknown"}
    )
    assert missing_name.status == 400
    assert invalid_type.status == 400
    async with session_scope() as session:
        assert (await session.scalar(select(User))) is None


@pytest.mark.asyncio
async def test_login_me_and_logout_round_trip(sent):
    await _make_user()

    _, login = await app.asgi_client.post(
        "/api/auth/login/",
        json={"email": "florist@example.com", "password": "flowers-are-nice"},
    )
    assert login.status == 200
    assert login.json == {
        "authenticated": True,
        "approved": True,
        "business_name": "Fern & Fig",
    }

    _, me = await app.asgi_client.get("/api/auth/me/")
    assert me.json["authenticated"] is True

    await app.asgi_client.post("/api/auth/logout/")

    _, after = await app.asgi_client.get("/api/auth/me/")
    assert after.json["authenticated"] is False


@pytest.mark.asyncio
async def test_login_rejects_a_bad_password(sent):
    await _make_user()

    _, response = await app.asgi_client.post(
        "/api/auth/login/",
        json={"email": "florist@example.com", "password": "wrong-password"},
    )

    assert response.status == 400
