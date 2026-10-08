"""Public retail catalogue and guest checkout.

Retail is the same product and order system as wholesale, filtered to
``channel=retail | both``. Retail buyers do not have accounts, so checkout
requires contact details instead of a session, and the resulting order stores
those details directly.
"""

from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit

from sanic import Blueprint
from sanic.response import json
from sqlalchemy import select, update

from ..db import session_scope
from ..emails import send_order_emails
from ..models import FlowerListing, Order
from ..orders import StockError, reserve_order
from .catalog import _listing_payload
from ..settings import get_settings

bp = Blueprint("retail", url_prefix="/api")

FULFILLMENTS = {"pickup", "delivery"}


def _stripe_product_data(item: dict, settings) -> dict:
    """Build Stripe's richer hosted-checkout product summary."""
    description = " · ".join(
        value
        for value in (item.get("variety"), item.get("color"), item.get("stem_notes"))
        if value
    )
    product_data = {"name": item["name"]}
    if description:
        product_data["description"] = description[:500]

    if item.get("photo"):
        media_base = settings.media_url.rstrip("/")
        image_url = (
            f"{media_base}/{item['photo']}"
            if urlsplit(media_base).scheme in {"http", "https"}
            else urljoin(settings.retail_checkout_success_url, f"{media_base}/{item['photo']}")
        )
        parsed_image = urlsplit(image_url)
        if parsed_image.scheme == "https" and parsed_image.netloc:
            product_data["images"] = [image_url]
    return product_data


@bp.get("/retail/flowers/")
async def retail_flowers(request):
    """Public list of offerings available to retail customers."""
    async with session_scope() as session:
        result = await session.execute(
            select(FlowerListing)
            .where(
                FlowerListing.active.is_(True),
                FlowerListing.channel.in_(["retail", "both"]),
            )
            .order_by(FlowerListing.sort_order, FlowerListing.name, FlowerListing.id)
        )
        listings = result.scalars().all()
    # Every listed item is orderable except the sold-out ones, which stay
    # visible so shoppers can see the catalogue rather than a blank grid.
    return json([_listing_payload(listing) for listing in listings])


@bp.post("/retail/checkout/")
async def retail_checkout(request):
    """Guest checkout for standard retail offerings via Stripe."""
    data = request.json or {}
    items = data.get("items", [])
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip()
    phone = str(data.get("phone", "")).strip()
    fulfillment = str(data.get("fulfillment", "pickup")).strip() or "pickup"
    delivery_address = str(data.get("delivery_address", "")).strip()
    pickup_window = str(data.get("pickup_window", "")).strip()
    notes = str(data.get("notes", "")).strip()

    errors: dict[str, list[str]] = {}
    if not items:
        errors["items"] = ["Your cart is empty."]
    if not name:
        errors["name"] = ["This field is required."]
    if not email or "@" not in email:
        errors["email"] = ["Enter a valid email address."]
    if fulfillment not in FULFILLMENTS:
        errors["fulfillment"] = ["Choose pickup or delivery."]
    if fulfillment == "delivery" and not delivery_address:
        errors["delivery_address"] = ["A delivery address is required."]
    if errors:
        return json(errors, status=400)

    settings = get_settings()
    delivery_fee = settings.retail_delivery_fee if fulfillment == "delivery" else Decimal("0")

    try:
        async with session_scope() as session:
            order, items_context = await reserve_order(
                session,
                items=items,
                channel="retail",
                customer_name=name,
                customer_email=email,
                customer_phone=phone,
                fulfillment=fulfillment,
                delivery_fee=delivery_fee,
                pickup_window=pickup_window,
                delivery_address=delivery_address,
                notes=notes,
            )
            order_id = order.id
    except (StockError, InvalidOperation) as error:
        return json({"detail": str(error)}, status=409)

    if not settings.stripe_secret_key:
        async with session_scope() as session:
            await session.execute(
                update(Order).where(Order.id == order_id).values(status="paid")
            )
            await session.commit()
        send_order_emails(
            order_id=order_id,
            channel="retail",
            customer_name=name,
            fulfillment=fulfillment,
            pickup_window=pickup_window,
            delivery_address=delivery_address,
            delivery_fee=delivery_fee,
            customer_email=email,
            items=items_context,
        )
        return json({"order_id": order_id, "checkout_url": ""}, status=201)

    import stripe

    stripe.api_key = settings.stripe_secret_key
    stripe_session = stripe.checkout.Session.create(
        mode="payment",
        customer_email=email,
        success_url=settings.retail_checkout_success_url,
        cancel_url=settings.retail_checkout_cancel_url,
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": _stripe_product_data(item, settings),
                    "unit_amount": int(Decimal(item["price"]) * 100),
                },
                "quantity": item["quantity"],
            }
            for item in items_context
        ]
        + ([
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": "Delivery"},
                    "unit_amount": int(delivery_fee * 100),
                },
                "quantity": 1,
            }
        ] if delivery_fee > 0 else []),
        metadata={"order_id": str(order_id)},
    )
    async with session_scope() as session:
        await session.execute(
            update(Order)
            .where(Order.id == order_id)
            .values(stripe_session_id=stripe_session.id)
        )
        await session.commit()
    return json({"order_id": order_id, "checkout_url": stripe_session.url}, status=201)
