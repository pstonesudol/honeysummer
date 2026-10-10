from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.admin import CSRF_COOKIE
from app.auth import hash_password
from app.db import session_scope
from app.models import (
    FlowerListing,
    Inquiry,
    InventoryMovement,
    Order,
    OrderItem,
    OrderNotification,
    User,
    WeddingQuote,
)
from app.operations_report import operations_rows
from app.reconcile import record_run
from app.server import app


@pytest.mark.asyncio
async def test_product_channel_and_waste_reports_keep_gross_and_stock_separate():
    # Midnight in Eastern time is not always midnight UTC.
    eastern = ZoneInfo("America/New_York")
    today = datetime.now(eastern).date()
    start = datetime.combine(today, datetime.min.time(), eastern).astimezone(UTC)
    async with session_scope() as db:
        db.add(User(email="owner@example.com", password_hash=hash_password("password"), is_admin=True))
        flower = FlowerListing(name="=Unsafe flower", price=Decimal("99.00"), channel="both", quantity_available=7)
        db.add(flower)
        await db.flush()
        db.add_all(
            [
                InventoryMovement(
                    listing_id=flower.id,
                    kind="waste",
                    delta=-2,
                    units=2,
                    reason="@Damaged",
                    source="admin",
                    created_at=start + timedelta(minutes=1),
                ),
                InventoryMovement(
                    listing_id=flower.id,
                    kind="count",
                    delta=-1,
                    units=1,
                    reason="Missing",
                    source="admin",
                    created_at=start + timedelta(minutes=2),
                ),
                InventoryMovement(
                    listing_id=flower.id,
                    kind="waste",
                    delta=-1,
                    units=1,
                    reason="Old",
                    source="admin",
                    created_at=start - timedelta(minutes=1),
                ),
            ]
        )
        paid = Order(
            channel="retail",
            status="paid",
            payment_method="cash",
            delivery_fee=Decimal("2.00"),
            created_at=start + timedelta(minutes=1),
            items=[
                OrderItem(
                    listing_id=flower.id, name_snapshot="=Unsafe flower", price_snapshot=Decimal("3.00"), quantity=2
                ),
                OrderItem(name_snapshot="Custom bunch", price_snapshot=Decimal("4.00"), quantity=1),
            ],
        )
        refunded = Order(
            channel="wholesale",
            status="refunded",
            payment_method="stripe_checkout",
            delivery_fee=Decimal("0.00"),
            created_at=start + timedelta(minutes=2),
            items=[
                OrderItem(
                    listing_id=flower.id, name_snapshot="=Unsafe flower", price_snapshot=Decimal("5.00"), quantity=1
                )
            ],
        )
        pending = Order(
            channel="retail",
            status="pending",
            payment_method="stripe_checkout",
            delivery_fee=Decimal("0.00"),
            created_at=start + timedelta(minutes=3),
            items=[
                OrderItem(
                    listing_id=flower.id, name_snapshot="=Unsafe flower", price_snapshot=Decimal("5.00"), quantity=8
                )
            ],
        )
        db.add_all([paid, refunded, pending])
        await db.flush()
        inquiry = Inquiry(kind="wedding", name="Review customer", email="review@example.com")
        db.add(inquiry)
        await db.flush()
        db.add(WeddingQuote(inquiry_id=inquiry.id, status="review", draft={}, snapshot={}, activity=[]))
        db.add(OrderNotification(order_id=paid.id, recipient="customer", attempts=2))
        await db.commit()
        waste, products, channels = await operations_rows(db, today, today)
    assert len(waste) == 1 and waste[0]["units"] == 2
    assert sum(row["units"] for row in products) == 4
    assert sum(row["gross"] for row in products) == Decimal("15.00")
    assert {(row["channel"], row["status"], row["gross"]) for row in channels} == {
        ("retail", "paid", Decimal("12.00")),
        ("wholesale", "refunded", Decimal("5.00")),
    }
    _, anonymous = await app.asgi_client.get("/admin/reports/operations?format=csv")
    assert anonymous.status == 302
    await app.asgi_client.get("/admin/login")
    await app.asgi_client.post(
        "/admin/login",
        data=dict(email="owner@example.com", password="password", csrf_token=app.asgi_client.cookies.get(CSRF_COOKIE)),
    )
    query = f"from={today}&to={today}"
    _, page = await app.asgi_client.get(f"/admin/reports/operations?{query}")
    assert page.status == 200 and "Products, channels &amp; waste" in page.text
    assert "Missing" not in page.text and "@Damaged" in page.text
    _, export = await app.asgi_client.get(f"/admin/reports/operations?{query}&format=csv")
    assert export.status == 200
    assert "'=Unsafe flower" in export.text and "'@Damaged" in export.text
    _, invalid = await app.asgi_client.get("/admin/reports/operations?from=2026-15-30")
    assert invalid.status == 400
    _, attention = await app.asgi_client.get("/admin/operations/attention")
    assert attention.status == 200
    assert "Wedding quote #1" in attention.text and "Order #1" in attention.text
    assert "<td>2</td>" in attention.text
    await record_run(["Order #1: check Stripe"], applied=False, full=False)
    _, attention = await app.asgi_client.get("/admin/operations/attention")
    assert "Order #1: check Stripe" in attention.text and "1 finding" in attention.text
