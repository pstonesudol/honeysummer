from decimal import Decimal

import pytest

from app.auth import hash_password
from app.db import session_scope
from app.models import FlowerListing, FloristProfile, User
from app.server import app


async def _make_user(email: str, approved: bool) -> None:
    async with session_scope() as session:
        user = User(
            email=email, password_hash=hash_password("flowers-are-nice"), is_active=True
        )
        session.add(
            FloristProfile(business_name="Fern & Fig", approved=approved, user=user)
        )
        await session.commit()


async def _login(email: str) -> None:
    await app.asgi_client.post(
        "/api/auth/login/", json={"email": email, "password": "flowers-are-nice"}
    )


@pytest.mark.asyncio
async def test_requires_authentication():
    _, response = await app.asgi_client.get("/api/flowers/")

    assert response.status == 403


@pytest.mark.asyncio
async def test_lists_active_wholesale_and_both_for_approved_florists():
    await _make_user("florist@example.com", approved=True)
    async with session_scope() as session:
        session.add_all(
            [
                FlowerListing(name="Dahlia", price=Decimal("2.50"), channel="both", quantity_available=10),
                FlowerListing(name="Retail only", price=Decimal("1.00"), channel="retail", quantity_available=5),
                FlowerListing(name="Hidden", price=Decimal("1.00"), channel="wholesale", active=False, quantity_available=5),
            ]
        )
        await session.commit()
    await _login("florist@example.com")

    _, response = await app.asgi_client.get("/api/flowers/")

    assert response.status == 200
    assert [item["name"] for item in response.json] == ["Dahlia"]
    assert response.json[0]["price"] == "2.50"
    assert response.json[0]["available"] is True


@pytest.mark.asyncio
async def test_unapproved_accounts_see_no_catalog():
    await _make_user("pending@example.com", approved=False)
    async with session_scope() as session:
        session.add(
            FlowerListing(name="Dahlia", price=Decimal("2.50"), channel="wholesale", quantity_available=10)
        )
        await session.commit()
    await _login("pending@example.com")

    _, response = await app.asgi_client.get("/api/flowers/")

    assert response.status == 200
    assert response.json == []
