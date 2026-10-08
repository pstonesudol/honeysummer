from decimal import Decimal
from unittest import mock

import pytest
from sqlalchemy import select

from app import emails
from app.auth import hash_password
from app.db import session_scope
from app.models import FlowerListing, FloristProfile, Order, OrderItem, User
from app.server import app
from app.settings import get_settings


@pytest.fixture
def sent(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(emails, "send_email", lambda **kwargs: calls.append(kwargs))
    return calls


@pytest.fixture
def stripe_off(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "debug", True)
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "")


@pytest.fixture
def stripe_on(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_123")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")


async def _make_user(email: str = "florist@example.com", approved: bool = True) -> None:
    async with session_scope() as session:
        user = User(
            email=email, password_hash=hash_password("flowers-are-nice"), is_active=True
        )
        session.add(
            FloristProfile(business_name="Fern & Fig", approved=approved, user=user)
        )
        await session.commit()


async def _login(email: str = "florist@example.com") -> None:
    await app.asgi_client.post(
        "/api/auth/login/", json={"email": email, "password": "flowers-are-nice"}
    )


async def _add_listing(
    quantity: int = 10,
    sold_out: bool = False,
    delivery_fee: str = "0",
    delivery_fee_mode: str = "per_listing",
) -> int:
    async with session_scope() as session:
        listing = FlowerListing(
            name="Dahlia",
            price=Decimal("2.50"),
            channel="wholesale",
            quantity_available=quantity,
            sold_out=sold_out,
            delivery_fee=Decimal(delivery_fee),
            delivery_fee_mode=delivery_fee_mode,
        )
        session.add(listing)
        await session.commit()
        return listing.id


async def _checkout(items: list[dict], **extra):
    return await app.asgi_client.post(
        "/api/checkout/", json={"items": items, **extra}
    )


@pytest.mark.asyncio
async def test_requires_approval(sent, stripe_off):
    await _make_user(approved=False)
    await _login()
    listing_id = await _add_listing()

    _, response = await _checkout([{"id": listing_id, "quantity": 1}])

    assert response.status == 403


@pytest.mark.asyncio
async def test_requires_authentication(sent, stripe_off):
    listing_id = await _add_listing()

    _, response = await _checkout([{"id": listing_id, "quantity": 1}])

    assert response.status == 403


@pytest.mark.asyncio
async def test_empty_cart_is_rejected(sent, stripe_off):
    await _make_user()
    await _login()

    _, response = await _checkout([])

    assert response.status == 400


@pytest.mark.asyncio
async def test_successful_order_holds_stock_and_snapshots_price(sent, stripe_off):
    await _make_user()
    listing_id = await _add_listing(quantity=10)
    await _login()

    _, response = await _checkout([{"id": listing_id, "quantity": 3}])

    assert response.status == 201
    assert response.json["checkout_url"] == ""
    assert response.json["order_reference"] == f"HS{response.json['order_id']:06d}"
    async with session_scope() as session:
        listing = await session.get(FlowerListing, listing_id)
        order = (await session.execute(select(Order))).scalar_one()
        item = (await session.execute(select(OrderItem))).scalar_one()
    assert listing.quantity_available == 7
    assert order.status == "paid"
    assert item.quantity == 3
    assert item.price_snapshot == Decimal("2.50")
    assert item.name_snapshot == "Dahlia"
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_insufficient_stock_is_rejected_and_nothing_held(sent, stripe_off):
    await _make_user()
    listing_id = await _add_listing(quantity=10)
    await _login()

    _, response = await _checkout([{"id": listing_id, "quantity": 11}])

    assert response.status == 409
    async with session_scope() as session:
        listing = await session.get(FlowerListing, listing_id)
    assert listing.quantity_available == 10
    async with session_scope() as session:
        assert (await session.execute(select(Order))).scalars().all() == []


@pytest.mark.asyncio
async def test_sold_out_or_unknown_listings_are_rejected(sent, stripe_off):
    await _make_user()
    listing_id = await _add_listing(quantity=5, sold_out=True)
    await _login()

    _, sold_out = await _checkout([{"id": listing_id, "quantity": 1}])
    _, unknown = await _checkout([{"id": 999999, "quantity": 1}])

    assert sold_out.status == 409
    assert unknown.status == 409


@pytest.mark.asyncio
async def test_configured_checkout_returns_a_stripe_session_url(sent, stripe_on):
    await _make_user()
    listing_id = await _add_listing(quantity=5)
    await _login()
    session = mock.Mock(id="cs_test_1", url="https://checkout.stripe.com/cs_test_1")

    with mock.patch("stripe.checkout.Session.create", return_value=session) as create:
        _, response = await _checkout([{"id": listing_id, "quantity": 1}])

    assert response.status == 201
    assert response.json["checkout_url"] == "https://checkout.stripe.com/cs_test_1"
    async with session_scope() as db:
        order = await db.get(Order, response.json["order_id"])
    assert order.status == "pending"
    assert order.stripe_session_id == "cs_test_1"
    assert create.called


@pytest.mark.asyncio
async def test_wholesale_delivery_uses_listing_fees_in_stripe_not_client_amount(sent, stripe_on):
    await _make_user()
    listing_id = await _add_listing(
        quantity=5, delivery_fee="7.50", delivery_fee_mode="per_unit"
    )
    await _login()
    stripe_session = mock.Mock(id="cs_delivery", url="https://checkout.stripe.com/cs_delivery")

    with mock.patch("stripe.checkout.Session.create", return_value=stripe_session) as create:
        _, response = await _checkout(
            [{"id": listing_id, "quantity": 2}],
            fulfillment="delivery",
            delivery_address="17 Garden Lane",
            delivery_fee="0.01",  # Client-supplied fees must have no effect.
        )

    assert response.status == 201
    async with session_scope() as db:
        order = await db.get(Order, response.json["order_id"])
    assert order.fulfillment == "delivery"
    assert order.delivery_address == "17 Garden Lane"
    assert order.delivery_fee == Decimal("15.00")
    line_items = create.call_args.kwargs["line_items"]
    assert line_items[-1]["price_data"]["product_data"]["name"] == "Delivery"
    assert line_items[-1]["price_data"]["unit_amount"] == 1500
    assert line_items[-1]["quantity"] == 1


@pytest.mark.asyncio
async def test_wholesale_pickup_is_free_and_saves_window(sent, stripe_off):
    await _make_user()
    listing_id = await _add_listing(delivery_fee="8.00")
    await _login()

    _, response = await _checkout(
        [{"id": listing_id, "quantity": 1}],
        fulfillment="pickup",
        pickup_window="Friday morning",
    )

    assert response.status == 201
    async with session_scope() as db:
        order = await db.get(Order, response.json["order_id"])
    assert order.delivery_fee == Decimal("0")
    assert order.pickup_window == "Friday morning"


@pytest.mark.asyncio
async def test_wholesale_delivery_fee_is_in_confirmation_email(sent, stripe_off):
    await _make_user()
    listing_id = await _add_listing(delivery_fee="8.00")
    await _login()
    _, response = await _checkout(
        [{"id": listing_id, "quantity": 2}],
        fulfillment="delivery",
        delivery_address="17 Garden Lane",
    )

    assert response.status == 201
    assert "Delivery fee: $8.00" in sent[0]["body"]


@pytest.mark.asyncio
async def test_wholesale_delivery_requires_address_and_valid_fulfillment(sent, stripe_off):
    await _make_user()
    listing_id = await _add_listing()
    await _login()
    items = [{"id": listing_id, "quantity": 1}]

    _, missing = await _checkout(items, fulfillment="delivery")
    _, invalid = await _checkout(items, fulfillment="courier")

    assert missing.status == 400
    assert invalid.status == 400
    async with session_scope() as db:
        assert (await db.execute(select(Order))).scalars().all() == []


@pytest.mark.asyncio
async def test_wholesale_checkout_rejects_a_retail_only_listing(sent, stripe_off):
    await _make_user()
    async with session_scope() as session:
        listing = FlowerListing(
            name="Retail only",
            price=Decimal("1.00"),
            channel="retail",
            quantity_available=5,
        )
        session.add(listing)
        await session.commit()
        listing_id = listing.id
    await _login()

    _, response = await _checkout([{"id": listing_id, "quantity": 1}])

    assert response.status == 409


async def _seed_pending_order() -> tuple[int, int]:
    async with session_scope() as session:
        user = User(
            email="florist@example.com",
            password_hash=hash_password("flowers-are-nice"),
            is_active=True,
        )
        listing = FlowerListing(
            name="Dahlia",
            price=Decimal("2.50"),
            channel="wholesale",
            quantity_available=3,
        )
        session.add_all([user, listing])
        await session.flush()
        order = Order(customer_id=user.id, status="pending", stripe_session_id="cs_seed")
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
        return order.id, listing.id


async def _post_webhook(event: dict):
    with mock.patch("stripe.Webhook.construct_event", return_value=event):
        return await app.asgi_client.post(
            "/api/stripe/webhook/",
            json=event,
            headers={"stripe-signature": "sig"},
        )


@pytest.mark.asyncio
async def test_webhook_completed_marks_paid_and_emails_both(sent, stripe_on):
    order_id, _ = await _seed_pending_order()

    _, response = await _post_webhook(
        {
            "type": "checkout.session.completed",
            "id": "evt_paid_wholesale",
            "data": {"object": {"id": "cs_seed", "metadata": {"order_id": str(order_id)}, "currency": "usd", "amount_total": 500, "payment_status": "paid"}},
        }
    )

    assert response.status == 200
    async with session_scope() as session:
        order = await session.get(Order, order_id)
    assert order.status == "paid"
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_webhook_expired_releases_held_stock(sent, stripe_on):
    order_id, listing_id = await _seed_pending_order()

    _, response = await _post_webhook(
        {
            "type": "checkout.session.expired",
            "id": "evt_expired_wholesale",
            "data": {"object": {"id": "cs_seed", "metadata": {"order_id": str(order_id)}}},
        }
    )

    assert response.status == 200
    async with session_scope() as session:
        order = await session.get(Order, order_id)
        listing = await session.get(FlowerListing, listing_id)
    assert order.status == "expired"
    assert listing.quantity_available == 5


@pytest.mark.asyncio
async def test_webhook_invalid_signature_returns_400(sent, stripe_on):
    with mock.patch("stripe.Webhook.construct_event", side_effect=Exception("bad")):
        _, response = await app.asgi_client.post(
            "/api/stripe/webhook/",
            json={"type": "irrelevant"},
            headers={"stripe-signature": "sig"},
        )

    assert response.status == 400
