"""Global cart retries, payment proof and channel/access boundaries."""

from decimal import Decimal
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app import emails
from app.auth import COOKIE_NAME, create_session_token, hash_password
from app.db import session_scope
from app.models import FloristProfile, FlowerListing, InventoryMovement, Order, User
from app.server import app
from app.settings import get_settings


@pytest.fixture(autouse=True)
def local_payments(monkeypatch):
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "")
    monkeypatch.setattr(emails, "send_email", lambda **kwargs: None)


async def listing(channel="both", quantity=5):
    async with session_scope() as db:
        flower = FlowerListing(name="Dahlias", price=Decimal("5.00"), quantity_available=quantity, channel=channel)
        db.add(flower)
        await db.commit()
        return flower.id


async def florist(approved=True, active=True):
    async with session_scope() as db:
        user = User(email=f"{uuid4()}@example.com", password_hash=hash_password("flowers-password"), is_active=active)
        db.add(FloristProfile(user=user, business_name="Synthetic studio", approved=approved))
        await db.commit()
        return user.id


def cookie(uid):
    app.asgi_client.cookies.set(COOKIE_NAME, create_session_token(uid))


async def retail(flower, key, **extra):
    return await app.asgi_client.post(
        "/api/retail/checkout/",
        json={
            "name": "Synthetic Buyer",
            "email": "buyer@example.com",
            "checkout_key": key,
            "items": [{"id": flower, "quantity": 2, "price": "5.00"}],
            **extra,
        },
    )


@pytest.mark.asyncio
async def test_retry_paid_attempt_never_deducts_twice_or_exposes_contact():
    flower, key = await listing(), str(uuid4())
    _, first = await retail(flower, key)
    _, second = await retail(flower, key)
    assert first.status == 201 and second.status == 200
    assert first.json["order_id"] == second.json["order_id"]
    _, status = await app.asgi_client.get(f"/api/cart/checkout/{key}/")
    assert status.json["status"] == "paid"
    assert status.headers["cache-control"] == "no-store"
    assert not {"email", "customer_email", "delivery_address", "items"}.intersection(status.json)
    async with session_scope() as db:
        assert await db.scalar(select(func.count()).select_from(Order)) == 1
        assert (await db.get(FlowerListing, flower)).quantity_available == 3


@pytest.mark.asyncio
async def test_pending_retry_cancel_and_release_are_safe(monkeypatch):
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test_cart")
    flower, key = await listing(), str(uuid4())
    remote = SimpleNamespace(id="cs_cart", url="https://checkout.stripe.com/synthetic")
    with mock.patch("stripe.checkout.Session.create", return_value=remote) as create:
        _, first = await retail(flower, key)
        _, again = await retail(flower, key)
    assert create.call_count == 1
    assert first.json["checkout_url"] == again.json["checkout_url"]
    _, status = await app.asgi_client.get(f"/api/cart/checkout/{key}/?checkout=success")
    assert status.json["status"] == "pending"  # Redirects never establish payment.
    with mock.patch("stripe.checkout.Session.retrieve", return_value=SimpleNamespace(status="complete")):
        _, blocked = await app.asgi_client.delete(f"/api/cart/checkout/{key}/")
    assert blocked.status == 409
    with (
        mock.patch("stripe.checkout.Session.retrieve", return_value=SimpleNamespace(status="open")),
        mock.patch("stripe.checkout.Session.expire", return_value=SimpleNamespace(status="expired")),
    ):
        _, cancelled = await app.asgi_client.delete(f"/api/cart/checkout/{key}/")
        _, duplicate = await app.asgi_client.delete(f"/api/cart/checkout/{key}/")
    assert cancelled.json["status"] == "cancelled" and duplicate.status == 409
    _, retry = await retail(flower, key)
    assert retry.json["status"] == "cancelled"
    async with session_scope() as db:
        assert (await db.get(FlowerListing, flower)).quantity_available == 5
        assert (
            await db.scalar(
                select(func.count()).select_from(InventoryMovement).where(InventoryMovement.kind == "release")
            )
            == 1
        )


@pytest.mark.asyncio
async def test_signed_delayed_payment_only_clears_when_paid(monkeypatch):
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test_cart")
    flower, key = await listing(), str(uuid4())
    with mock.patch(
        "stripe.checkout.Session.create",
        return_value=SimpleNamespace(id="cs_cart", url="https://checkout.stripe.com/synthetic"),
    ):
        _, checkout = await retail(flower, key)
    obj = {
        "id": "cs_cart",
        "metadata": {"order_id": str(checkout.json["order_id"])},
        "currency": "usd",
        "amount_total": 1000,
        "payment_status": "unpaid",
    }
    for kind, expected in [
        ("checkout.session.completed", "pending"),
        ("checkout.session.async_payment_succeeded", "paid"),
        ("checkout.session.async_payment_succeeded", "paid"),
    ]:
        event = {"id": f"evt_{kind}", "type": kind, "data": {"object": obj}}
        with mock.patch("stripe.Webhook.construct_event", return_value=event):
            await app.asgi_client.post("/api/stripe/webhook/", json=event, headers={"stripe-signature": "synthetic"})
        _, status = await app.asgi_client.get(f"/api/cart/checkout/{key}/")
        assert status.json["status"] == expected


@pytest.mark.asyncio
async def test_wrong_channels_price_changes_and_shared_stock():
    retail_only, wholesale_only = await listing("retail"), await listing("wholesale")
    _, wrong = await retail(wholesale_only, str(uuid4()))
    assert wrong.status == 409
    _, price = await retail(retail_only, str(uuid4()), items=[{"id": retail_only, "quantity": 1, "price": "0.01"}])
    assert price.status == 409 and "price" in price.json["detail"]
    uid = await florist()
    cookie(uid)
    _, wrong = await app.asgi_client.post(
        "/api/checkout/", json={"items": [{"id": retail_only, "quantity": 1}], "checkout_key": str(uuid4())}
    )
    assert wrong.status == 409
    shared = await listing(quantity=3)
    _, bought = await retail(shared, str(uuid4()))
    assert bought.status == 201
    _, contested = await app.asgi_client.post(
        "/api/checkout/", json={"items": [{"id": shared, "quantity": 2}], "checkout_key": str(uuid4())}
    )
    assert contested.status == 409


@pytest.mark.asyncio
async def test_wholesale_attempt_is_scoped_to_active_approved_account():
    flower, key, uid = await listing(), str(uuid4()), await florist()
    cookie(uid)
    _, checkout = await app.asgi_client.post(
        "/api/checkout/", json={"items": [{"id": flower, "quantity": 1}], "checkout_key": key}
    )
    assert checkout.status == 201
    app.asgi_client.cookies.clear()
    _, anonymous = await app.asgi_client.get(f"/api/cart/checkout/{key}/")
    assert anonymous.status == 403
    cookie(await florist())
    _, other = await app.asgi_client.get(f"/api/cart/checkout/{key}/")
    assert other.status == 403
    cookie(uid)
    async with session_scope() as db:
        profile = await db.scalar(select(FloristProfile).where(FloristProfile.user_id == uid))
        profile.approved = False
        await db.commit()
    _, pending = await app.asgi_client.get(f"/api/cart/checkout/{key}/")
    assert pending.status == 403
    async with session_scope() as db:
        (await db.get(User, uid)).is_active = False
        await db.commit()
    _, me = await app.asgi_client.get("/api/auth/me/")
    assert me.json["authenticated"] is False


@pytest.mark.asyncio
async def test_invalid_and_unknown_keys_and_cross_channel_retry():
    flower, key = await listing(), str(uuid4())
    _, invalid = await retail(flower, "not-a-uuid")
    assert invalid.status == 400
    _, missing = await app.asgi_client.get(f"/api/cart/checkout/{key}/")
    assert missing.status == 404
    await retail(flower, key)
    cookie(await florist())
    _, cross = await app.asgi_client.post(
        "/api/checkout/", json={"items": [{"id": flower, "quantity": 1}], "checkout_key": key}
    )
    assert cross.status == 403
