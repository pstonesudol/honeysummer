from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app import emails
from app.admin import CSRF_COOKIE, _active_href
from app.auth import hash_password
from app.db import session_scope
from app.models import (
    Announcement,
    FloristProfile,
    FlowerListing,
    Inquiry,
    InventoryMovement,
    Order,
    OrderItem,
    User,
)
from app.security_views import CSRF_COOKIE as SECURITY_CSRF_COOKIE
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
    return await app.asgi_client.post("/admin/login", data={"email": email, "password": password, "csrf_token": token})


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


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/admin/", "/admin/"),
        ("/admin/orders", "/admin/orders"),
        ("/admin/orders/12", "/admin/orders"),
        ("/admin/orders/manual/new", "/admin/orders"),
        ("/admin/orders/preparation", "/admin/orders/preparation"),
        ("/admin/proposals/3", "/admin/proposals/"),
        ("/admin/reports/balances", "/admin/reports/balances"),
        ("/admin/flowers?season=fall", "/admin/flowers"),
        ("/admin/nope", "/admin/"),
    ],
)
def test_active_href_picks_most_specific_nav(path, expected):
    assert _active_href(path) == expected


@pytest.mark.asyncio
async def test_sidebar_marks_the_current_section_active():
    await _make_admin()
    await _login()

    _, orders = await app.asgi_client.get("/admin/orders")
    assert orders.status == 200
    assert 'href="/admin/orders" class="is-active" aria-current="page"' in orders.text


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

    _, response = await app.asgi_client.post(f"/admin/announcements/{announcement_id}/delete", data={})

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
    assert f"FL-{listing_id:04d}" in listing_page.text
    token = await _csrf("/admin/flowers")

    _, response = await app.asgi_client.post(f"/admin/flowers/{listing_id}/delete", data={"csrf_token": token})

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
                listing_id=listing.id,
                kind="opening",
                delta=0,
                units=0,
                reason="Initial stock",
                source="admin",
            )
        )
        await session.commit()
        listing_id = listing.id
    await _login()
    token = await _csrf("/admin/flowers")

    _, response = await app.asgi_client.post(f"/admin/flowers/{listing_id}/delete", data={"csrf_token": token})

    assert response.status == 409
    async with session_scope() as session:
        assert await session.get(FlowerListing, listing_id) is not None


@pytest.mark.asyncio
async def test_form_post_without_csrf_is_rejected():
    await _make_admin()
    await _login()

    _, response = await app.asgi_client.post("/admin/announcements/new", data={"text": "Nope"})

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
        user_id = profile.user_id
    await _login()
    sent.clear()
    await app.asgi_client.get("/admin/security/access")
    token = app.asgi_client.cookies.get(SECURITY_CSRF_COOKIE)

    _, response = await app.asgi_client.post(
        "/admin/security/access",
        data={"csrf_token": token, "action": "approve", "user_id": user_id, "reason": "Verified business"},
    )

    assert response.status == 302
    async with session_scope() as session:
        profile = await session.get(FloristProfile, profile_id)
    assert profile.approved is True
    assert len(sent) == 2
    assert sent[0]["to"] == "florist@example.com"
    assert "approve" in sent[0]["body"]

    await app.asgi_client.post(
        "/admin/security/access",
        data={"csrf_token": token, "action": "approve", "user_id": user_id, "reason": "Verified business"},
    )
    assert len(sent) == 2


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

    _, response = await app.asgi_client.post(f"/admin/orders/{order_id}/action/cancel", data={"csrf_token": token})

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
        session.add(
            OrderItem(
                order_id=order.id,
                listing_id=1,
                name_snapshot="Peony bunch",
                price_snapshot=Decimal("12.50"),
                quantity=3,
            )
        )
        await session.commit()
        order_id = order.id
    await _login()

    _, listing = await app.asgi_client.get("/admin/orders")
    _, detail = await app.asgi_client.get(f"/admin/orders/{order_id}")

    assert listing.status == 200
    assert "Dana Bloom" in listing.text
    assert "Retail" in listing.text
    assert detail.status == 200
    assert "Dana Bloom" in detail.text
    assert "Order items" in detail.text
    assert "Peony bunch" in detail.text
    assert "37.50" in detail.text
    assert f"HS{order_id:06d}" in detail.text


@pytest.mark.asyncio
async def test_fulfillment_schedule_dashboard_and_packing_slip():
    await _make_admin()
    async with session_scope() as session:
        listing = FlowerListing(name="Peonies", price=Decimal("8.00"), quantity_available=2, low_stock_threshold=3)
        order = Order(status="paid", channel="retail", customer_name="June", customer_email="june@example.com")
        session.add_all([listing, order])
        await session.flush()
        session.add(
            OrderItem(
                order_id=order.id,
                listing_id=listing.id,
                name_snapshot="Peonies",
                price_snapshot=Decimal("8.00"),
                quantity=2,
            )
        )
        await session.commit()
        order_id = order.id
    await _login()
    _, dashboard = await app.asgi_client.get("/admin/")
    assert "Peonies" in dashboard.text
    token = await _csrf(f"/admin/orders/{order_id}")

    day = (datetime.now(ZoneInfo("America/New_York")) + timedelta(days=1)).date().isoformat()
    form = dict(
        csrf_token=token,
        fulfillment_date=day,
        fulfillment_time="09:30",
        fulfillment_state="ready",
        internal_notes="Bring twine",
    )
    _, saved = await app.asgi_client.post(f"/admin/orders/{order_id}/fulfillment", data=form)
    assert saved.status == 302
    _, dashboard = await app.asgi_client.get("/admin/")
    assert f"HS{order_id:06d}" in dashboard.text
    assert "Ready" in dashboard.text
    _, slip = await app.asgi_client.get(f"/admin/orders/{order_id}/packing-slip")
    assert slip.status == 200
    assert "Bring twine" in slip.text
    assert "Peonies" in slip.text
    token = await _csrf(f"/admin/orders/{order_id}")
    form.update(csrf_token=token, fulfillment_state="completed")
    _, completed = await app.asgi_client.post(f"/admin/orders/{order_id}/fulfillment", data=form)
    assert completed.status == 302
    async with session_scope() as session:
        order = await session.get(Order, order_id)
        listing = await session.get(FlowerListing, listing.id)
    assert order.fulfilled_at is not None
    assert len(order.activity) == 2
    assert listing.quantity_available == 2  # preparation never deducts stock again
    token = await _csrf(f"/admin/orders/{order_id}")
    form.update(csrf_token=token, fulfillment_state="preparing")
    _, reopened = await app.asgi_client.post(f"/admin/orders/{order_id}/fulfillment", data=form)
    assert reopened.status == 409


@pytest.mark.asyncio
async def test_unpaid_fulfillment_and_invalid_schedule_are_rejected():
    await _make_admin()
    async with session_scope() as session:
        order = Order(status="pending", customer_name="May")
        session.add(order)
        await session.commit()
        order_id = order.id
    await _login()
    token = await _csrf(f"/admin/orders/{order_id}")
    path = f"/admin/orders/{order_id}/fulfillment"
    _, invalid = await app.asgi_client.post(
        path, data={"csrf_token": token, "fulfillment_date": "2026-20-80", "fulfillment_state": "ready"}
    )
    assert invalid.status == 400
    _, unpaid = await app.asgi_client.post(path, data={"csrf_token": token, "fulfillment_state": "ready"})
    assert unpaid.status == 409
    _, no_csrf = await app.asgi_client.post(path, data={"fulfillment_state": "ready"})
    assert no_csrf.status == 403


@pytest.mark.asyncio
async def test_manual_paid_order_stock_custom_lines_and_idempotency(monkeypatch):

    monkeypatch.setattr(emails, "send_email", lambda **kwargs: None)
    await _make_admin()
    async with session_scope() as db:
        flower = FlowerListing(
            name="Ranunculus", price=Decimal("3.00"), quantity_available=4, delivery_fee=Decimal("2.00"), channel="both"
        )
        db.add(flower)
        await db.commit()
        flower_id = flower.id
    await _login()
    token = await _csrf("/admin/orders/manual/new")
    form = dict(
        csrf_token=token,
        manual_key=str(uuid4()),
        customer_name="Ada",
        customer_email="ada@example.com",
        fulfillment="delivery",
        delivery_address="123 Main St",
        payment_method="external",
        payment_reference="pi_dashboard_123",
        payment_confirmed="on",
        amount_collected="18.00",
        listing_1=str(flower_id),
        quantity_1="2",
        name_2="Custom bouquet",
        quantity_2="1",
        price_2="10.00",
    )
    path = "/admin/orders/manual/new"
    _, wrong_total = await app.asgi_client.post(path, data={**form, "amount_collected": "12.00"})
    assert wrong_total.status == 400
    assert wrong_total.json["field"] == "amount_collected"
    _, created = await app.asgi_client.post(path, data=form)
    assert created.status == 302
    _, repeated = await app.asgi_client.post(path, data=form)
    assert repeated.status == 302
    async with session_scope() as db:
        orders = (await db.scalars(select(Order))).all()
        assert len(orders) == 1
        order = orders[0]
        flower = await db.get(FlowerListing, flower_id)
        lines = (await db.scalars(select(OrderItem).where(OrderItem.order_id == order.id))).all()
        movements = (await db.scalars(select(InventoryMovement).where(InventoryMovement.order_id == order.id))).all()
    assert order.status == "paid" and order.payment_method == "external"
    assert order.delivery_fee == Decimal("2.00")
    assert flower.quantity_available == 2
    assert len(lines) == 2 and any(item.listing_id is None for item in lines)
    assert len([entry for entry in movements if entry.kind == "market_sale"]) == 1


@pytest.mark.asyncio
async def test_manual_order_rejects_short_stock_without_order():

    await _make_admin()
    async with session_scope() as db:
        flower = FlowerListing(name="Dahlia", price=Decimal("3.00"), quantity_available=1)
        db.add(flower)
        await db.commit()
        flower_id = flower.id
    await _login()
    token = await _csrf("/admin/orders/manual/new")
    _, response = await app.asgi_client.post(
        "/admin/orders/manual/new",
        data=dict(
            csrf_token=token,
            manual_key=str(uuid4()),
            customer_name="Ada",
            customer_email="ada@example.com",
            fulfillment="pickup",
            payment_method="cash",
            payment_confirmed="on",
            amount_collected="6.00",
            listing_1=str(flower_id),
            quantity_1="2",
        ),
    )
    assert response.status == 400
    async with session_scope() as db:
        assert (await db.scalars(select(Order))).all() == []
        assert (await db.get(FlowerListing, flower_id)).quantity_available == 1


@pytest.mark.asyncio
async def test_sales_ledger_includes_manual_and_protects_csv_cells():
    await _make_admin()
    async with session_scope() as db:
        order = Order(
            status="paid",
            customer_name="=HYPERLINK(foo)",
            customer_email="x@example.com",
            payment_method="cash",
            payment_reference="+unsafe",
            channel="retail",
        )
        db.add(order)
        await db.flush()
        db.add(
            OrderItem(
                order_id=order.id, listing_id=None, name_snapshot="Bouquet", quantity=1, price_snapshot=Decimal("20.00")
            )
        )
        await db.commit()
    await _login()
    _, page = await app.asgi_client.get("/admin/reports/sales")
    assert page.status == 200 and "20.00" in page.text and "cash" in page.text
    _, exported = await app.asgi_client.get("/admin/reports/sales?format=csv")
    assert exported.status == 200
    assert "'=HYPERLINK(foo)" in exported.text
    assert "'+unsafe" in exported.text
    _, invalid = await app.asgi_client.get("/admin/reports/sales?from=bad")
    assert invalid.status == 400


@pytest.mark.asyncio
async def test_bulk_restock_and_physical_count_keep_audit_trail():
    await _make_admin()
    async with session_scope() as db:
        flower = FlowerListing(name="Zinnia", price=Decimal("3.00"), quantity_available=2)
        db.add(flower)
        await db.commit()
        flower_id = flower.id
    await _login()
    token = await _csrf("/admin/inventory/stock")
    _, overview = await app.asgi_client.get("/admin/inventory/stock")
    assert overview.status == 200 and "Zinnia" in overview.text
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    _, restocked = await app.asgi_client.post(
        "/admin/inventory/bulk-restock",
        data=dict(csrf_token=token, source="Harvest 42", reason="Garden", listing_1=str(flower_id), units_1="3"),
    )
    assert restocked.status == 302
    token = await _csrf(f"/admin/flowers/{flower_id}/inventory")
    _, counted = await app.asgi_client.post(
        f"/admin/flowers/{flower_id}/count", data=dict(csrf_token=token, on_hand="4", reason="Weekly count")
    )
    assert counted.status == 302
    async with session_scope() as db:
        flower = await db.get(FlowerListing, flower_id)
        movements = (await db.scalars(select(InventoryMovement).where(InventoryMovement.listing_id == flower_id))).all()
    assert flower.quantity_available == 4
    assert any(entry.kind == "restock" and entry.delta == 3 for entry in movements)
    assert any(entry.kind == "count" and entry.delta == -1 for entry in movements)
    url = f"/admin/flowers/{flower_id}/inventory"
    _, filtered = await app.asgi_client.get(f"{url}?kind=restock&q=Garden")
    assert filtered.status == 200 and "1 matching movement" in filtered.text
    assert "Weekly count" not in filtered.text
    _, exported = await app.asgi_client.get(f"{url}?kind=restock&format=csv")
    assert exported.status == 200 and "Harvest 42" in exported.text
    assert "Weekly count" not in exported.text
    _, invalid_page = await app.asgi_client.get(f"{url}?page=abc")
    assert invalid_page.status == 400


@pytest.mark.asyncio
async def test_inquiry_followup_and_customer_history():
    await _make_admin()
    async with session_scope() as db:
        inquiry = Inquiry(kind="wedding", name="Ava", email="ava@example.com", message="Wedding flowers")
        order = Order(status="paid", customer_name="Ava", customer_email="ava@example.com")
        db.add_all([inquiry, order])
        await db.commit()
        inquiry_id = inquiry.id
    await _login()
    token = await _csrf(f"/admin/inquiries/{inquiry_id}")
    _, recorded = await app.asgi_client.post(
        f"/admin/inquiries/{inquiry_id}/correspondence",
        data=dict(
            csrf_token=token, direction="received", subject="Wedding date", summary="Client confirmed October 12."
        ),
    )
    assert recorded.status == 302
    _, inquiry_page = await app.asgi_client.get(f"/admin/inquiries/{inquiry_id}")
    assert inquiry_page.status == 200 and "Client confirmed October 12." in inquiry_page.text
    token = await _csrf(f"/admin/inquiries/{inquiry_id}")
    _, saved = await app.asgi_client.post(
        f"/admin/inquiries/{inquiry_id}/follow-up",
        data=dict(csrf_token=token, stage="contacted", follow_up_date="2026-10-15", internal_notes="Send quote"),
    )
    assert saved.status == 302
    _, history = await app.asgi_client.get("/admin/customers?email=ava@example.com")
    assert history.status == 200 and "Wedding flowers" not in history.text
    assert "wedding" in history.text and "HS" in history.text
    async with session_scope() as db:
        inquiry = await db.get(Inquiry, inquiry_id)
    assert inquiry.stage == "contacted" and not inquiry.handled
    token = await _csrf(f"/admin/inquiries/{inquiry_id}")
    _, closed = await app.asgi_client.post(
        f"/admin/inquiries/{inquiry_id}/follow-up", data=dict(csrf_token=token, stage="closed", internal_notes="Done")
    )
    assert closed.status == 302
    async with session_scope() as db:
        assert (await db.get(Inquiry, inquiry_id)).handled is True


@pytest.mark.asyncio
async def test_duplicate_listing_does_not_copy_stock_and_bulk_price_updates():
    await _make_admin()
    async with session_scope() as db:
        flower = FlowerListing(name="Anemone", price=Decimal("4.00"), quantity_available=8, active=True)
        db.add(flower)
        await db.commit()
        flower_id = flower.id
    await _login()
    token = await _csrf("/admin/flowers")
    _, seasonal = await app.asgi_client.post(
        "/admin/flowers/bulk-update",
        data=dict(csrf_token=token, listing_ids=str(flower_id), action="season", value="fall"),
    )
    assert seasonal.status == 302
    _, filtered = await app.asgi_client.get("/admin/flowers?season=fall")
    assert filtered.status == 200 and "Anemone" in filtered.text
    _, empty = await app.asgi_client.get("/admin/flowers?season=spring")
    assert empty.status == 200 and "Anemone" not in empty.text
    token = await _csrf(f"/admin/flowers/{flower_id}")
    _, copied = await app.asgi_client.post(f"/admin/flowers/{flower_id}/duplicate", data={"csrf_token": token})
    assert copied.status == 302
    async with session_scope() as db:
        clone = await db.scalar(select(FlowerListing).where(FlowerListing.name == "Anemone (copy)"))
        assert clone.quantity_available == 0 and clone.active is False
        clone_id = clone.id
    token = await _csrf("/admin/flowers")
    _, updated = await app.asgi_client.post(
        "/admin/flowers/bulk-update",
        data=dict(csrf_token=token, listing_ids=f"{flower_id}, {clone_id}", action="price", value="5.25"),
    )
    assert updated.status == 302
    async with session_scope() as db:
        assert (await db.get(FlowerListing, flower_id)).price == Decimal("5.25")
        assert (await db.get(FlowerListing, clone_id)).price == Decimal("5.25")
