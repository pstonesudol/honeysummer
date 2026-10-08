from decimal import Decimal

import pytest
from sqlalchemy import select

from app import emails
from app.admin import CSRF_COOKIE
from app.auth import hash_password
from app.db import session_scope
from app.models import (
    Announcement, FlowerListing, FloristProfile, InventoryMovement, Order,
    OrderItem, User,
)
from app.server import app
from app.settings import get_settings

ADMIN_EMAIL = "boss@example.com"
ADMIN_PASSWORD = "honey-summer-admin"


async def _make_admin(email: str = ADMIN_EMAIL, is_admin: bool = True) -> None:
    async with session_scope() as session:
        session.add(
            User(
                email=email,
                password_hash=hash_password(ADMIN_PASSWORD),
                is_admin=is_admin,
            )
        )
        await session.commit()


async def _login(email: str = ADMIN_EMAIL, password: str = ADMIN_PASSWORD):
    await app.asgi_client.get("/admin/login")
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    return await app.asgi_client.post(
        "/admin/login", data={"email": email, "password": password, "csrf_token": token}
    )


async def _csrf(path: str) -> str:
    await app.asgi_client.get(path)
    return app.asgi_client.cookies.get(CSRF_COOKIE)


@pytest.mark.asyncio
async def test_dashboard_requires_login():
    _, response = await app.asgi_client.get("/admin/")

    assert response.status == 302
    assert "/admin/login" in response.headers["location"]


@pytest.mark.asyncio
async def test_non_admin_cannot_log_in():
    await _make_admin(is_admin=False)

    _, response = await _login()

    assert response.status == 400


@pytest.mark.asyncio
async def test_admin_can_log_in_and_see_the_dashboard():
    await _make_admin()

    _, login = await _login()
    assert login.status == 302

    _, dashboard = await app.asgi_client.get("/admin/")
    assert dashboard.status == 200
    assert "Dashboard" in dashboard.text


@pytest.mark.asyncio
async def test_create_announcement_through_the_form():
    await _make_admin()
    await _login()
    token = await _csrf("/admin/announcements/new")

    _, response = await app.asgi_client.post(
        "/admin/announcements/new",
        data={
            "text": "Spring flowers are here",
            "link_url": "https://example.com/shop",
            "link_label": "Shop now",
            "active": "on",
            "csrf_token": token,
        },
    )

    assert response.status == 302
    async with session_scope() as session:
        announcement = (await session.execute(select(Announcement))).scalar_one()
    assert announcement.text == "Spring flowers are here"
    assert announcement.active is True


@pytest.mark.asyncio
async def test_admin_can_configure_listing_delivery_fee():
    await _make_admin()
    await _login()
    token = await _csrf("/admin/flowers/new")

    _, response = await app.asgi_client.post(
        "/admin/flowers/new",
        data={
            "name": "Dahlias",
            "price": "12.00",
            "quantity_available": "7",
            "delivery_fee": "4.50",
            "delivery_fee_mode": "per_order",
            "channel": "both",
            "active": "on",
            "csrf_token": token,
        },
    )

    assert response.status == 302
    async with session_scope() as session:
        listing = (await session.execute(select(FlowerListing))).scalar_one()
    assert listing.price == Decimal("12.00")
    assert listing.quantity_available == 7
    assert listing.delivery_fee == Decimal("4.50")
    assert listing.delivery_fee_mode == "per_order"

    token = await _csrf(f"/admin/flowers/{listing.id}")
    _, updated = await app.asgi_client.post(
        f"/admin/flowers/{listing.id}",
        data={
            "name": "Dahlias",
            "price": "12.00",
            "quantity_available": "7",
            "delivery_fee": "2.00",
            "delivery_fee_mode": "per_unit",
            "channel": "both",
            "active": "on",
            "csrf_token": token,
        },
    )
    assert updated.status == 302
    async with session_scope() as session:
        listing = await session.get(FlowerListing, listing.id)
    assert listing.delivery_fee == Decimal("2.00")
    assert listing.delivery_fee_mode == "per_unit"


@pytest.mark.asyncio
async def test_admin_rejects_negative_listing_delivery_fee():
    await _make_admin()
    await _login()
    token = await _csrf("/admin/flowers/new")
    _, response = await app.asgi_client.post(
        "/admin/flowers/new",
        data={
            "name": "Dahlias",
            "price": "12.00",
            "delivery_fee": "-2.00",
            "delivery_fee_mode": "per_unit",
            "csrf_token": token,
        },
    )
    assert response.status == 400
    async with session_scope() as session:
        assert (await session.execute(select(FlowerListing))).scalars().all() == []


@pytest.mark.asyncio
async def test_admin_can_delete_an_entry_with_csrf():
    await _make_admin()
    async with session_scope() as session:
        announcement = Announcement(text="Remove me")
        session.add(announcement)
        await session.commit()
        announcement_id = announcement.id
    await _login()
    _, listing = await app.asgi_client.get("/admin/announcements")
    assert "Delete" in listing.text
    token = await _csrf("/admin/announcements")
    _, response = await app.asgi_client.post(
        f"/admin/announcements/{announcement_id}/delete", data={"csrf_token": token}
    )

    assert response.status == 302
    async with session_scope() as session:
        assert await session.get(Announcement, announcement_id) is None


@pytest.mark.asyncio
async def test_delete_without_csrf_is_rejected():
    await _make_admin()
    async with session_scope() as session:
        announcement = Announcement(text="Keep me")
        session.add(announcement)
        await session.commit()
        announcement_id = announcement.id
    await _login()

    _, response = await app.asgi_client.post(
        f"/admin/announcements/{announcement_id}/delete", data={}
    )

    assert response.status == 403
    async with session_scope() as session:
        assert await session.get(Announcement, announcement_id) is not None


@pytest.mark.asyncio
async def test_admin_can_delete_listing_without_order_or_inventory_history():
    await _make_admin()
    async with session_scope() as session:
        listing = FlowerListing(name="Unused", price=Decimal("5.00"))
        session.add(listing)
        await session.commit()
        listing_id = listing.id
    await _login()
    _, listing_page = await app.asgi_client.get("/admin/flowers")
    assert "Delete" in listing_page.text
    token = await _csrf("/admin/flowers")

    _, response = await app.asgi_client.post(
        f"/admin/flowers/{listing_id}/delete", data={"csrf_token": token}
    )

    assert response.status == 302
    async with session_scope() as session:
        assert await session.get(FlowerListing, listing_id) is None


@pytest.mark.asyncio
async def test_admin_cannot_delete_listing_with_inventory_history():
    await _make_admin()
    async with session_scope() as session:
        listing = FlowerListing(name="Tracked", price=Decimal("5.00"))
        session.add(listing)
        await session.flush()
        session.add(
            InventoryMovement(
                listing_id=listing.id, kind="opening", delta=0, units=0,
                reason="Initial stock", source="admin",
            )
        )
        await session.commit()
        listing_id = listing.id
    await _login()
    token = await _csrf("/admin/flowers")

    _, response = await app.asgi_client.post(
        f"/admin/flowers/{listing_id}/delete", data={"csrf_token": token}
    )

    assert response.status == 409
    async with session_scope() as session:
        assert await session.get(FlowerListing, listing_id) is not None


@pytest.mark.asyncio
async def test_form_post_without_csrf_is_rejected():
    await _make_admin()
    await _login()

    _, response = await app.asgi_client.post(
        "/admin/announcements/new", data={"text": "Nope"}
    )

    assert response.status == 403
    async with session_scope() as session:
        assert (await session.execute(select(Announcement))).scalars().all() == []


@pytest.mark.asyncio
async def test_approve_florist_action(monkeypatch):
    sent = []
    monkeypatch.setattr(emails, "send_email", lambda **kwargs: sent.append(kwargs))
    await _make_admin()
    async with session_scope() as session:
        profile = FloristProfile(
            business_name="Fern & Fig",
            approved=False,
            user=User(email="florist@example.com", password_hash=hash_password("x")),
        )
        session.add(profile)
        await session.commit()
        profile_id = profile.id
    await _login()
    token = await _csrf("/admin/florists")

    _, response = await app.asgi_client.post(
        f"/admin/florists/{profile_id}/action/approve", data={"csrf_token": token}
    )

    assert response.status == 302
    async with session_scope() as session:
        profile = await session.get(FloristProfile, profile_id)
    assert profile.approved is True
    assert len(sent) == 1
    assert sent[0]["to"] == "florist@example.com"
    assert "approved" in sent[0]["subject"]

    token = await _csrf("/admin/florists")
    await app.asgi_client.post(
        f"/admin/florists/{profile_id}/action/approve", data={"csrf_token": token}
    )
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_cancel_order_action_releases_stock(monkeypatch):
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "")
    await _make_admin()
    async with session_scope() as session:
        user = User(email="florist@example.com", password_hash=hash_password("x"))
        listing = FlowerListing(name="Dahlia", price=Decimal("2.50"), quantity_available=3)
        session.add_all([user, listing])
        await session.flush()
        order = Order(customer_id=user.id, status="pending")
        session.add(order)
        await session.flush()
        session.add(
            OrderItem(
                order_id=order.id,
                listing_id=listing.id,
                name_snapshot="Dahlia",
                price_snapshot=Decimal("2.50"),
                quantity=2,
            )
        )
        await session.commit()
        order_id, listing_id = order.id, listing.id
    await _login()
    token = await _csrf("/admin/orders")

    _, response = await app.asgi_client.post(
        f"/admin/orders/{order_id}/action/cancel", data={"csrf_token": token}
    )

    assert response.status == 302
    async with session_scope() as session:
        order = await session.get(Order, order_id)
        listing = await session.get(FlowerListing, listing_id)
    assert order.status == "cancelled"
    assert listing.quantity_available == 5


@pytest.mark.asyncio
async def test_florist_list_and_edit_render_relationship_columns():
    await _make_admin()
    async with session_scope() as session:
        profile = FloristProfile(
            business_name="Fern & Fig",
            approved=False,
            user=User(email="florist@example.com", password_hash=hash_password("x")),
        )
        session.add(profile)
        await session.commit()
        profile_id = profile.id
    await _login()

    _, listing = await app.asgi_client.get("/admin/florists")

    assert listing.status == 200
    assert "Fern" in listing.text

    _, edit = await app.asgi_client.get(f"/admin/florists/{profile_id}")

    assert edit.status == 200
    assert "florist@example.com" in edit.text


@pytest.mark.asyncio
async def test_orders_list_renders_customer_column():
    await _make_admin()
    async with session_scope() as session:
        user = User(email="buyer@example.com", password_hash=hash_password("x"))
        session.add(user)
        await session.flush()
        session.add(Order(customer_id=user.id, status="paid"))
        await session.commit()
    await _login()

    _, listing = await app.asgi_client.get("/admin/orders")

    assert listing.status == 200
    assert "buyer@example.com" in listing.text


@pytest.mark.asyncio
async def test_orders_list_renders_guest_orders_and_channel():
    await _make_admin()
    async with session_scope() as session:
        order = Order(
            channel="retail",
            customer_name="Dana Bloom",
            customer_email="dana@example.com",
            status="paid",
        )
        session.add(order)
        await session.flush()
        session.add(OrderItem(
            order_id=order.id,
            listing_id=1,
            name_snapshot="Peony bunch",
            price_snapshot=Decimal("12.50"),
            quantity=3,
        ))
        await session.commit()
        order_id = order.id
    await _login()

    _, listing = await app.asgi_client.get("/admin/orders")
    _, detail = await app.asgi_client.get(f"/admin/orders/{order_id}")

    assert listing.status == 200
    assert "Dana Bloom" in listing.text
    assert "retail" in listing.text
    assert detail.status == 200
    assert "Dana Bloom" in detail.text
    assert "Order items" in detail.text
    assert "Peony bunch" in detail.text
    assert "37.50" in detail.text
