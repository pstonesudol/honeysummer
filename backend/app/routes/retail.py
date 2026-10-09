"""Public retail catalogue and guest checkout.

Retail is the same product and order system as wholesale, filtered to
``channel=retail | both``. Retail buyers do not have accounts, so checkout
requires contact details instead of a session, and the resulting order stores
those details directly.
"""

import logging
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit

from sanic import Blueprint
from sanic.response import json
from sqlalchemy import select

from ..db import session_scope
from ..models import FlowerListing
from ..orders import StockError, reserve_order
from ..payments import complete_without_stripe, create_checkout
from .catalog import _listing_payload
from ..settings import get_settings

bp = Blueprint("retail", url_prefix="/api")
logger = logging.getLogger(__name__)

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
    if not settings.debug and (not settings.stripe_secret_key or not settings.stripe_webhook_secret):
        return json({"detail": "Online payments are not configured."}, status=503)
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
                pickup_window=pickup_window,
                delivery_address=delivery_address,
                notes=notes,
            )
            order_id = order.id
            order_reference = order.order_reference
            delivery_fee = order.delivery_fee
    except (StockError, InvalidOperation) as error:
        return json({"detail": str(error)}, status=409)

    if not settings.stripe_secret_key:
        await complete_without_stripe(order_id)
        return json({"order_id": order_id, "order_reference": order_reference, "checkout_url": ""}, status=201)

    try:
        stripe_session = await create_checkout(
            order_id,
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
        )
    except Exception:
        logger.exception("Unable to create retail Stripe Checkout for order %s", order_id)
        return json({"detail": "Unable to start payment. Please try again."}, status=503)
    return json({"order_id": order_id, "order_reference": order_reference, "checkout_url": stripe_session.url}, status=201)
