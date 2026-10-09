"""Phase 6 stock journal, Stripe transitions, and recovery regression tests."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import mock

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import emails
from app.admin import CSRF_COOKIE
from app.auth import hash_password
from app.db import session_scope
from app.models import FlowerListing, InventoryMovement, Order, OrderNotification, User
from app.orders import reserve_order
from app.payments import reconcile
from app.server import app
from app.settings import get_settings


async def listing_and_order(*, key: bool = True):
    async with session_scope() as db:
        listing = FlowerListing(name="Dahlia", price=Decimal("5.00"), quantity_available=4, channel="retail")
        db.add(listing)
        await db.commit()
        listing_id = listing.id
    async with session_scope() as db:
        order, _ = await reserve_order(
            db, items=[{"id": listing_id, "quantity": 2}], channel="retail",
            customer_email="buyer@example.com",
        )
        order_id = order.id
        if key:
            order.stripe_session_id = "cs_inventory"
            await db.commit()
    return listing_id, order_id


async def webhook(order_id: int, event_type: str, *, event_id="evt_inventory", **fields):
    obj = {"id": "cs_inventory", "metadata": {"order_id": str(order_id)}, **fields}
    event = {"id": event_id, "type": event_type, "data": {"object": obj}}
    with mock.patch("stripe.Webhook.construct_event", return_value=event):
        return await app.asgi_client.post(
            "/api/stripe/webhook/", json=event, headers={"stripe-signature": "sig"}
        )


async def admin_login():
    async with session_scope() as db:
        db.add(User(email="operator@example.com", password_hash=hash_password("flowers-admin"), is_admin=True))
        await db.commit()
    await app.asgi_client.get("/admin/login")
    return await app.asgi_client.post("/admin/login", data={
        "email": "operator@example.com", "password": "flowers-admin",
        "csrf_token": app.asgi_client.cookies.get(CSRF_COOKIE),
    })


async def csrf(path):
    await app.asgi_client.get(path)
    return app.asgi_client.cookies.get(CSRF_COOKIE)


@pytest.mark.asyncio
async def test_paid_webhook_once_and_late_expiry_cannot_restore_stock(monkeypatch):
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test")
    sent = []
    monkeypatch.setattr(emails, "send_email", lambda **kw: sent.append(kw))
    listing_id, order_id = await listing_and_order()

    for _ in range(2):
        _, response = await webhook(
            order_id, "checkout.session.completed", payment_status="paid",
            currency="usd", amount_total=1000, payment_intent="pi_inventory",
        )
        assert response.status == 200
    _, late = await webhook(order_id, "checkout.session.expired", event_id="evt_late")

    assert late.status == 409
    async with session_scope() as db:
        listing = await db.get(FlowerListing, listing_id)
        order = await db.get(Order, order_id)
        movements = (await db.scalars(select(InventoryMovement).where(InventoryMovement.listing_id == listing_id))).all()
    assert order.status == "paid"
    assert listing.quantity_available == 2
    assert [(m.kind, m.delta) for m in movements] == [("opening", 4), ("reserve", -2), ("sale", 0)]
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_repeated_expiry_releases_only_once(monkeypatch):
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test")
    listing_id, order_id = await listing_and_order()
    for event_id in ("evt_expire_first", "evt_expire_second"):
        _, response = await webhook(order_id, "checkout.session.expired", event_id=event_id)
        assert response.status == 200
    async with session_scope() as db:
        assert (await db.get(FlowerListing, listing_id)).quantity_available == 4
        assert (await db.get(Order, order_id)).status == "expired"
        assert await db.scalar(select(func.count()).select_from(InventoryMovement).where(
            InventoryMovement.order_id == order_id, InventoryMovement.kind == "release"
        )) == 1


@pytest.mark.asyncio
async def test_paid_event_after_expiry_requires_review_not_a_silent_sale(monkeypatch):
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test")
    listing_id, order_id = await listing_and_order()
    await webhook(order_id, "checkout.session.expired", event_id="evt_expires")
    _, late_payment = await webhook(order_id, "checkout.session.completed", event_id="evt_late_paid",
                                    payment_status="paid", currency="usd", amount_total=1000)
    assert late_payment.status == 409
    async with session_scope() as db:
        assert (await db.get(Order, order_id)).status == "expired"
        assert (await db.get(FlowerListing, listing_id)).quantity_available == 4


@pytest.mark.asyncio
async def test_wrong_session_or_total_cannot_confirm_payment(monkeypatch):
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test")
    listing_id, order_id = await listing_and_order()
    _, wrong = await webhook(
        order_id, "checkout.session.completed", event_id="evt_wrong",
        id="cs_other", payment_status="paid", currency="usd", amount_total=1000,
    )
    _, amount = await webhook(
        order_id, "checkout.session.completed", event_id="evt_bad_amount",
        payment_status="paid", currency="usd", amount_total=10,
    )
    assert wrong.status == amount.status == 409
    async with session_scope() as db:
        assert (await db.get(Order, order_id)).status == "pending"
        assert (await db.get(FlowerListing, listing_id)).quantity_available == 2


@pytest.mark.asyncio
async def test_failed_stripe_creation_releases_hold(monkeypatch):
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test")
    async with session_scope() as db:
        db.add(FlowerListing(name="Market Bouquet", price=Decimal("20.00"), channel="retail", quantity_available=3))
        await db.commit()
    with mock.patch("stripe.checkout.Session.create", side_effect=RuntimeError("Stripe unavailable")):
        _, response = await app.asgi_client.post("/api/retail/checkout/", json={
            "items": [{"id": 1, "quantity": 2}], "name": "Dana", "email": "dana@example.com",
        })
    assert response.status == 503
    async with session_scope() as db:
        assert (await db.get(FlowerListing, 1)).quantity_available == 3
        assert (await db.scalar(select(Order))).status == "expired"


@pytest.mark.asyncio
async def test_reconciler_releases_orphaned_due_hold_and_reports_balance(monkeypatch):
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "")
    monkeypatch.setattr(get_settings(), "debug", True)
    listing_id, order_id = await listing_and_order(key=False)
    async with session_scope() as db:
        order = await db.get(Order, order_id)
        order.hold_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
    assert "orphaned pending hold" in " ".join(await reconcile())
    await reconcile(apply=True)
    assert await reconcile() == []
    async with session_scope() as db:
        assert (await db.get(FlowerListing, listing_id)).quantity_available == 4


@pytest.mark.asyncio
async def test_reconciler_does_not_release_unknown_stripe_session(monkeypatch):
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test")
    listing_id, order_id = await listing_and_order(key=False)
    async with session_scope() as db:
        order = await db.get(Order, order_id)
        order.hold_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
    assert "manual review" in " ".join(await reconcile(apply=True))
    async with session_scope() as db:
        assert (await db.get(Order, order_id)).status == "pending"
        assert (await db.get(FlowerListing, listing_id)).quantity_available == 2


@pytest.mark.asyncio
async def test_reconciler_fails_closed_when_production_job_lacks_stripe_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "")
    monkeypatch.setattr(get_settings(), "debug", False)
    listing_id, order_id = await listing_and_order(key=False)
    async with session_scope() as db:
        order = await db.get(Order, order_id)
        order.hold_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
    assert "manual review" in " ".join(await reconcile(apply=True))
    async with session_scope() as db:
        assert (await db.get(Order, order_id)).status == "pending"
        assert (await db.get(FlowerListing, listing_id)).quantity_available == 2


@pytest.mark.asyncio
async def test_delayed_payment_waits_for_success_and_refund_never_auto_restocks(monkeypatch):
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test")
    monkeypatch.setattr(emails, "send_email", lambda **kw: None)
    listing_id, order_id = await listing_and_order()
    _, completed = await webhook(
        order_id, "checkout.session.completed", event_id="evt_delayed",
        payment_status="unpaid", currency="usd", amount_total=1000,
    )
    assert completed.status == 200
    async with session_scope() as db:
        assert (await db.get(Order, order_id)).status == "pending"
    _, succeeded = await webhook(
        order_id, "checkout.session.async_payment_succeeded", event_id="evt_async",
        payment_status="paid", currency="usd", amount_total=1000,
        payment_intent="pi_inventory",
    )
    assert succeeded.status == 200
    _, refund = await webhook(
        order_id, "charge.refunded", event_id="evt_refund",
        payment_intent="pi_inventory", currency="usd", amount=1000, amount_refunded=1000,
    )
    assert refund.status == 200
    async with session_scope() as db:
        assert (await db.get(Order, order_id)).status == "refunded"
        assert (await db.get(FlowerListing, listing_id)).quantity_available == 2


@pytest.mark.asyncio
async def test_failed_email_retries_from_outbox(monkeypatch):
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "")
    sent = []
    def send(**kwargs):
        if not sent:
            sent.append("failed")
            raise RuntimeError("Email unavailable")
        sent.append(kwargs["to"])
    monkeypatch.setattr(emails, "send_email", send)
    _, order_id = await listing_and_order(key=False)
    from app.payments import complete_without_stripe
    await complete_without_stripe(order_id)
    async with session_scope() as db:
        assert await db.scalar(select(func.count()).select_from(OrderNotification).where(
            OrderNotification.sent_at.is_(None)
        )) == 1
    await reconcile(apply=True)
    assert sent == ["failed", get_settings().inquiry_notification_email, "buyer@example.com"]
    async with session_scope() as db:
        assert await db.scalar(select(func.count()).select_from(OrderNotification).where(
            OrderNotification.sent_at.is_(None)
        )) == 0


@pytest.mark.asyncio
async def test_admin_stock_changes_are_audited_and_direct_edits_ignored():
    await admin_login()
    token = await csrf("/admin/flowers/new")
    _, created = await app.asgi_client.post("/admin/flowers/new", data={
        "csrf_token": token, "name": "Dahlia", "price": "5.00", "quantity_available": "4",
        "channel": "retail", "active": "on", "delivery_fee_mode": "per_listing",
    })
    assert created.status == 302
    async with session_scope() as db:
        listing_id = (await db.scalar(select(FlowerListing.id)))
    token = await csrf(f"/admin/flowers/{listing_id}")
    _, edited = await app.asgi_client.post(f"/admin/flowers/{listing_id}", data={
        "csrf_token": token, "name": "Dahlia", "price": "5.00", "quantity_available": "100",
        "channel": "retail", "active": "on", "delivery_fee_mode": "per_listing",
    })
    assert edited.status == 302
    for kind, quantity, status in (("restock", "2", 302), ("waste", "3", 302), ("market_sale", "4", 409)):
        token = await csrf(f"/admin/flowers/{listing_id}/inventory")
        _, response = await app.asgi_client.post(f"/admin/flowers/{listing_id}/adjust", data={
            "csrf_token": token, "kind": kind, "quantity": quantity, "reason": "Market count",
        })
        assert response.status == status
    async with session_scope() as db:
        listing = await db.get(FlowerListing, listing_id)
        movements = (await db.scalars(select(InventoryMovement).where(
            InventoryMovement.listing_id == listing_id
        ).order_by(InventoryMovement.id))).all()
    _, inventory_page = await app.asgi_client.get(f"/admin/flowers/{listing_id}/inventory")
    assert inventory_page.status == 200
    assert "On hand: 3" in inventory_page.text
    assert "Market count" in inventory_page.text
    assert listing.quantity_available == 3
    assert [(m.kind, m.delta) for m in movements] == [
        ("opening", 0), ("restock", 4), ("restock", 2), ("waste", -3)
    ]
    assert await reconcile() == []


@pytest.mark.asyncio
async def test_database_rejects_negative_available_stock():
    async with session_scope() as db:
        db.add(FlowerListing(name="Bad stock", price=Decimal("5.00"), quantity_available=-1))
        with pytest.raises(IntegrityError):
            await db.commit()


@pytest.mark.asyncio
async def test_paid_order_cannot_cancel_and_refund_restock_only_once(monkeypatch):
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test")
    monkeypatch.setattr(emails, "send_email", lambda **kw: None)
    listing_id, order_id = await listing_and_order()
    await webhook(order_id, "checkout.session.completed", payment_status="paid",
                  currency="usd", amount_total=1000, payment_intent="pi_inventory")
    await admin_login()
    token = await csrf("/admin/orders")
    _, denied = await app.asgi_client.post(f"/admin/orders/{order_id}/action/cancel", data={"csrf_token": token})
    assert denied.status == 409
    token = await csrf("/admin/orders")
    _, fulfilled = await app.asgi_client.post(f"/admin/orders/{order_id}/action/fulfill", data={"csrf_token": token})
    assert fulfilled.status == 302
    async with session_scope() as db:
        assert (await db.get(Order, order_id)).fulfilled_at is not None
    _, refunded = await webhook(order_id, "charge.refunded", event_id="evt_return",
                                payment_intent="pi_inventory", currency="usd", amount=1000, amount_refunded=1000)
    assert refunded.status == 200
    for expected in (302, 409):
        token = await csrf("/admin/orders")
        _, response = await app.asgi_client.post(f"/admin/orders/{order_id}/action/restock", data={"csrf_token": token})
        assert response.status == expected
    async with session_scope() as db:
        assert (await db.get(FlowerListing, listing_id)).quantity_available == 4


@pytest.mark.asyncio
async def test_admin_cancels_only_unpayable_checkout(monkeypatch):
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test")
    listing_id, order_id = await listing_and_order()
    await admin_login()
    token = await csrf("/admin/orders")
    with mock.patch("stripe.checkout.Session.retrieve", return_value=mock.Mock(status="complete")):
        _, blocked = await app.asgi_client.post(
            f"/admin/orders/{order_id}/action/cancel", data={"csrf_token": token}
        )
    assert blocked.status == 409
    async with session_scope() as db:
        assert (await db.get(FlowerListing, listing_id)).quantity_available == 2
    token = await csrf("/admin/orders")
    with mock.patch("stripe.checkout.Session.retrieve", return_value=mock.Mock(status="expired")):
        _, cancelled = await app.asgi_client.post(
            f"/admin/orders/{order_id}/action/cancel", data={"csrf_token": token}
        )
    assert cancelled.status == 302
    _, late = await webhook(order_id, "checkout.session.expired", event_id="evt_cancel_late")
    assert late.status == 200
    async with session_scope() as db:
        assert (await db.get(FlowerListing, listing_id)).quantity_available == 4
        assert (await db.get(Order, order_id)).status == "cancelled"


@pytest.mark.asyncio
async def test_reconciler_checks_stripe_before_releasing_stale_hold(monkeypatch):
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test")
    listing_id, order_id = await listing_and_order()
    async with session_scope() as db:
        order = await db.get(Order, order_id)
        order.hold_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
    with mock.patch("stripe.checkout.Session.retrieve", return_value=mock.Mock(
        status="complete", payment_status="unpaid"
    )):
        assert "manual review" in " ".join(await reconcile(apply=True))
    async with session_scope() as db:
        assert (await db.get(FlowerListing, listing_id)).quantity_available == 2
    with mock.patch("stripe.checkout.Session.retrieve", return_value=mock.Mock(
        status="expired", payment_status="unpaid"
    )):
        assert "expired" in " ".join(await reconcile(apply=True))
    async with session_scope() as db:
        assert (await db.get(FlowerListing, listing_id)).quantity_available == 4


@pytest.mark.asyncio
async def test_partial_refund_requires_review_and_preserves_stock(monkeypatch):
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test")
    monkeypatch.setattr(emails, "send_email", lambda **kw: None)
    listing_id, order_id = await listing_and_order()
    await webhook(order_id, "checkout.session.completed", payment_status="paid",
                  currency="usd", amount_total=1000, payment_intent="pi_inventory")
    _, partial = await webhook(order_id, "charge.refunded", event_id="evt_partial",
                              payment_intent="pi_inventory", currency="usd",
                              amount=1000, amount_refunded=500)
    assert partial.status == 409
    async with session_scope() as db:
        assert (await db.get(Order, order_id)).status == "paid"
        assert (await db.get(FlowerListing, listing_id)).quantity_available == 2


@pytest.mark.asyncio
async def test_reconciler_catches_missed_full_refund(monkeypatch):
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test")
    monkeypatch.setattr(emails, "send_email", lambda **kw: None)
    listing_id, order_id = await listing_and_order()
    await webhook(order_id, "checkout.session.completed", payment_status="paid",
                  currency="usd", amount_total=1000, payment_intent="pi_inventory")
    charge = {"payment_intent": "pi_inventory", "currency": "usd", "amount": 1000,
              "amount_refunded": 1000}
    with mock.patch("stripe.checkout.Session.retrieve", return_value=mock.Mock(
        payment_status="paid", currency="usd", amount_total=1000
    )), mock.patch("stripe.PaymentIntent.retrieve", return_value={"latest_charge": charge}):
        assert "fully refunded" in " ".join(await reconcile(apply=True))
    async with session_scope() as db:
        assert (await db.get(Order, order_id)).status == "refunded"
        assert (await db.get(FlowerListing, listing_id)).quantity_available == 2
