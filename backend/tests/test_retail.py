from decimal import Decimal
from unittest import mock

import pytest
from sqlalchemy import select

from app import emails
from app.db import session_scope
from app.models import FlowerListing, Order, OrderItem
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


async def _add_listing(
    *,
    name: str = "Market Bouquet",
    price: str = "32.00",
    channel: str = "retail",
    quantity: int = 10,
    active: bool = True,
    sold_out: bool = False,
    sort_order: int = 0,
    variety: str = "",
    color: str = "",
    stem_notes: str = "",
    photo: str = "",
    delivery_fee: str = "0",
    delivery_fee_mode: str = "per_listing",
) -> int:
    async with session_scope() as session:
        listing = FlowerListing(
            name=name,
            price=Decimal(price),
            channel=channel,
            quantity_available=quantity,
            active=active,
            sold_out=sold_out,
            sort_order=sort_order,
            variety=variety,
            color=color,
            stem_notes=stem_notes,
            photo=photo,
            delivery_fee=Decimal(delivery_fee),
            delivery_fee_mode=delivery_fee_mode,
        )
        session.add(listing)
        await session.commit()
        return listing.id


async def _checkout(items: list[dict], **extra):
    payload = {
        "items": items,
        "name": "Dana Bloom",
        "email": "dana@example.com",
        **extra,
    }
    return await app.asgi_client.post("/api/retail/checkout/", json=payload)


@pytest.mark.asyncio
async def test_public_catalog_needs_no_auth_and_lists_retail_and_both():
    await _add_listing(name="Retail bunch", channel="retail", sort_order=2)
    await _add_listing(name="Both bunch", channel="both", sort_order=0)
    await _add_listing(name="Wholesale only", channel="wholesale")
    await _add_listing(name="Hidden", channel="retail", active=False)

    _, response = await app.asgi_client.get("/api/retail/flowers/")

    assert response.status == 200
    assert [item["name"] for item in response.json] == ["Both bunch", "Retail bunch"]
    assert response.json[0]["price"] == "32.00"
    assert response.json[0]["delivery_fee"] == "0.00"
    assert response.json[0]["delivery_fee_mode"] == "per_listing"


@pytest.mark.asyncio
async def test_guest_checkout_holds_stock_and_records_contact(sent, stripe_off):
    listing_id = await _add_listing(quantity=10)

    _, response = await _checkout([{"id": listing_id, "quantity": 2}])

    assert response.status == 201
    assert response.json["checkout_url"] == ""
    async with session_scope() as session:
        listing = await session.get(FlowerListing, listing_id)
        order = (await session.execute(select(Order))).scalar_one()
        item = (await session.execute(select(OrderItem))).scalar_one()
        order_id = order.id
    assert listing.quantity_available == 8
    assert order.status == "paid"
    assert order.channel == "retail"
    assert order.customer_id is None
    assert order.customer_name == "Dana Bloom"
    assert order.customer_email == "dana@example.com"
    assert item.quantity == 2
    assert item.price_snapshot == Decimal("32.00")
    assert len(sent) == 2
    assert response.json["order_id"] == order_id
    assert response.json["order_reference"] == f"HS{order_id:06d}"


@pytest.mark.asyncio
async def test_retail_checkout_rejects_wholesale_only_listing(sent, stripe_off):
    listing_id = await _add_listing(channel="wholesale")

    _, response = await _checkout([{"id": listing_id, "quantity": 1}])

    assert response.status == 409
    async with session_scope() as session:
        assert (await session.execute(select(Order))).scalars().all() == []


@pytest.mark.asyncio
async def test_retail_checkout_requires_contact_details(sent, stripe_off):
    listing_id = await _add_listing()

    _, missing_name = await app.asgi_client.post(
        "/api/retail/checkout/",
        json={"items": [{"id": listing_id, "quantity": 1}], "email": "dana@example.com"},
    )
    _, missing_email = await app.asgi_client.post(
        "/api/retail/checkout/",
        json={"items": [{"id": listing_id, "quantity": 1}], "name": "Dana"},
    )
    _, empty_cart = await app.asgi_client.post(
        "/api/retail/checkout/",
        json={"items": [], "name": "Dana", "email": "dana@example.com"},
    )

    assert missing_name.status == 400
    assert missing_email.status == 400
    assert empty_cart.status == 400


@pytest.mark.asyncio
async def test_retail_delivery_requires_an_address(sent, stripe_off):
    listing_id = await _add_listing()

    _, response = await _checkout([{"id": listing_id, "quantity": 1}], fulfillment="delivery")

    assert response.status == 400


@pytest.mark.asyncio
async def test_retail_delivery_applies_the_listing_fee(sent, stripe_off):
    listing_id = await _add_listing(delivery_fee="12.00")

    _, response = await _checkout(
        [{"id": listing_id, "quantity": 1}],
        fulfillment="delivery",
        delivery_address="12 Garden Lane, Mountain Top, PA",
    )

    assert response.status == 201
    async with session_scope() as session:
        order = (await session.execute(select(Order))).scalar_one()
    assert order.fulfillment == "delivery"
    assert order.delivery_fee == Decimal("12.00")
    assert order.delivery_address == "12 Garden Lane, Mountain Top, PA"
    assert "Delivery fee: $12.00" in sent[0]["body"]


@pytest.mark.asyncio
async def test_delivery_combines_all_three_listing_fee_modes(sent, stripe_off):
    per_listing = await _add_listing(delivery_fee="3.00", delivery_fee_mode="per_listing")
    per_unit = await _add_listing(delivery_fee="2.50", delivery_fee_mode="per_unit")
    lower = await _add_listing(delivery_fee="4.00", delivery_fee_mode="per_order")
    higher = await _add_listing(delivery_fee="9.00", delivery_fee_mode="per_order")

    _, response = await _checkout(
        [
            {"id": per_listing, "quantity": 2},
            {"id": per_unit, "quantity": 3},
            {"id": lower, "quantity": 1},
            {"id": higher, "quantity": 1},
        ],
        fulfillment="delivery",
        delivery_address="17 Garden Lane",
    )

    assert response.status == 201
    async with session_scope() as db:
        order = await db.get(Order, response.json["order_id"])
    assert order.delivery_fee == Decimal("19.50")  # 3 + 3 * 2.50 + max(4, 9)


@pytest.mark.asyncio
async def test_per_listing_fee_charged_once_for_repeated_cart_entries(sent, stripe_off):
    listing_id = await _add_listing(delivery_fee="3.00")
    _, response = await _checkout(
        [{"id": listing_id, "quantity": 1}, {"id": listing_id, "quantity": 2}],
        fulfillment="delivery",
        delivery_address="17 Garden Lane",
    )
    assert response.status == 201
    async with session_scope() as db:
        order = await db.get(Order, response.json["order_id"])
    assert order.delivery_fee == Decimal("3.00")


@pytest.mark.asyncio
async def test_insufficient_stock_is_rejected_and_nothing_held(sent, stripe_off):
    listing_id = await _add_listing(quantity=3)

    _, response = await _checkout([{"id": listing_id, "quantity": 4}])

    assert response.status == 409
    async with session_scope() as session:
        listing = await session.get(FlowerListing, listing_id)
        assert (await session.execute(select(Order))).scalars().all() == []
    assert listing.quantity_available == 3


@pytest.mark.asyncio
async def test_configured_retail_checkout_returns_a_stripe_session(sent, stripe_on):
    listing_id = await _add_listing(quantity=5)
    session = mock.Mock(id="cs_test_9", url="https://checkout.stripe.com/cs_test_9")

    with mock.patch("stripe.checkout.Session.create", return_value=session) as create:
        _, response = await _checkout([{"id": listing_id, "quantity": 1}])

    assert response.status == 201
    assert response.json["checkout_url"] == "https://checkout.stripe.com/cs_test_9"
    assert create.call_args.kwargs["success_url"] == (get_settings().retail_checkout_success_url)
    async with session_scope() as session:
        order = await session.get(Order, response.json["order_id"])
    assert order.status == "pending"
    assert order.stripe_session_id == "cs_test_9"


@pytest.mark.asyncio
async def test_stripe_checkout_includes_listing_thumbnail_and_description(sent, stripe_on, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "retail_checkout_success_url",
        "https://hellohoneysummer.com/order-flowers?checkout=success",
    )
    listing_id = await _add_listing(
        name="Market Bouquet",
        variety="Dahlia",
        color="Apricot",
        stem_notes="Seasonal mix",
        photo="flowers/bouquet.jpg",
    )
    session = mock.Mock(id="cs_test_image", url="https://checkout.stripe.com/cs_test_image")

    with mock.patch("stripe.checkout.Session.create", return_value=session) as create:
        _, response = await _checkout([{"id": listing_id, "quantity": 1}])

    assert response.status == 201
    product_data = create.call_args.kwargs["line_items"][0]["price_data"]["product_data"]
    assert product_data["description"] == "Dahlia · Apricot · Seasonal mix"
    assert product_data["images"] == ["https://hellohoneysummer.com/media/flowers/bouquet.jpg"]


@pytest.mark.asyncio
async def test_stripe_checkout_charges_configured_delivery_fee(sent, stripe_on, monkeypatch):
    listing_id = await _add_listing(quantity=5, delivery_fee="12.00")
    session = mock.Mock(id="cs_test_delivery", url="https://checkout.stripe.com/cs_test_delivery")

    with mock.patch("stripe.checkout.Session.create", return_value=session) as create:
        _, response = await _checkout(
            [{"id": listing_id, "quantity": 1}],
            fulfillment="delivery",
            delivery_address="12 Garden Lane, Mountain Top, PA",
        )

    assert response.status == 201
    line_items = create.call_args.kwargs["line_items"]
    assert line_items[-1]["price_data"]["product_data"]["name"] == "Delivery"
    assert line_items[-1]["price_data"]["unit_amount"] == 1200


async def _seed_pending_retail_order() -> tuple[int, int]:
    async with session_scope() as session:
        listing = FlowerListing(
            name="Market Bouquet",
            price=Decimal("32.00"),
            channel="retail",
            quantity_available=3,
        )
        session.add(listing)
        await session.flush()
        order = Order(
            channel="retail",
            customer_name="Dana Bloom",
            customer_email="dana@example.com",
            status="pending",
            stripe_session_id="cs_seed_retail",
        )
        session.add(order)
        await session.flush()
        session.add(
            OrderItem(
                order_id=order.id,
                listing_id=listing.id,
                name_snapshot="Market Bouquet",
                price_snapshot=Decimal("32.00"),
                quantity=2,
            )
        )
        await session.commit()
        return order.id, listing.id


@pytest.mark.asyncio
async def test_webhook_completes_a_guest_order_and_emails(sent, stripe_on):
    order_id, _ = await _seed_pending_retail_order()
    event = {
        "type": "checkout.session.completed",
        "id": "evt_paid_retail",
        "data": {
            "object": {
                "id": "cs_seed_retail",
                "metadata": {"order_id": str(order_id)},
                "currency": "usd",
                "amount_total": 6400,
                "payment_status": "paid",
            }
        },
    }

    with mock.patch("stripe.Webhook.construct_event", return_value=event):
        _, response = await app.asgi_client.post(
            "/api/stripe/webhook/", json=event, headers={"stripe-signature": "sig"}
        )

    assert response.status == 200
    async with session_scope() as session:
        order = await session.get(Order, order_id)
    assert order.status == "paid"
    assert len(sent) == 2
    assert sent[0]["to"] == "dana@example.com"


@pytest.mark.asyncio
async def test_webhook_email_includes_delivery_fee(sent, stripe_on):
    order_id, _ = await _seed_pending_retail_order()
    async with session_scope() as session:
        order = await session.get(Order, order_id)
        order.fulfillment = "delivery"
        order.delivery_fee = Decimal("12.00")
        await session.commit()

    event = {
        "type": "checkout.session.completed",
        "id": "evt_paid_retail_delivery",
        "data": {
            "object": {
                "id": "cs_seed_retail",
                "metadata": {"order_id": str(order_id)},
                "currency": "usd",
                "amount_total": 7600,
                "payment_status": "paid",
            }
        },
    }
    with mock.patch("stripe.Webhook.construct_event", return_value=event):
        _, response = await app.asgi_client.post(
            "/api/stripe/webhook/", json=event, headers={"stripe-signature": "sig"}
        )

    assert response.status == 200
    assert "Delivery fee: $12.00" in sent[0]["body"]
