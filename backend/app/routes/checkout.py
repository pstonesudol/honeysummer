"""Wholesale checkout and the Stripe webhook.

Inventory is held inside a transaction with row locks so concurrent checkouts
cannot oversell, mirroring the original Django implementation. Retail guest
checkout shares this machinery through :mod:`app.orders`.
"""

import logging
from decimal import Decimal, InvalidOperation

import stripe
from sanic import Blueprint
from sanic.response import json
from sqlalchemy import select

from ..auth import get_current_user
from ..db import session_scope
from ..models import WeddingInvoice
from ..orders import StockError, reserve_order
from ..payments import apply_checkout_event, complete_without_stripe, create_checkout
from ..proposals import apply_invoice_event
from ..settings import get_settings
from ..weddings import apply_wedding_invoice_event

bp = Blueprint("checkout", url_prefix="/api")
logger = logging.getLogger(__name__)


@bp.post("/checkout/")
async def checkout(request):
    """Reserve wholesale stock and start a Stripe Checkout session."""
    user = await get_current_user(request)
    if user is None:
        return json({"detail": "Authentication credentials were not provided."}, status=403)
    profile = user.profile
    if profile is None or not profile.approved:
        return json({"detail": "Wholesale approval is required."}, status=403)
    settings = get_settings()
    if not settings.debug and (not settings.stripe_secret_key or not settings.stripe_webhook_secret):
        return json({"detail": "Online payments are not configured."}, status=503)

    data = request.json or {}
    items = data.get("items", [])
    if not items:
        return json({"detail": "Your cart is empty."}, status=400)
    fulfillment = str(data.get("fulfillment", "pickup")).strip()
    delivery_address = str(data.get("delivery_address", "")).strip()
    if fulfillment not in ("pickup", "delivery"):
        return json({"detail": "Choose pickup or delivery."}, status=400)
    if fulfillment == "delivery" and not delivery_address:
        return json({"detail": "A delivery address is required."}, status=400)

    try:
        async with session_scope() as session:
            order, items_context = await reserve_order(
                session,
                items=items,
                channel="wholesale",
                customer_id=user.id,
                customer_email=user.email,
                fulfillment=fulfillment,
                pickup_window=str(data.get("pickup_window", "")),
                delivery_address=delivery_address,
            )
            order_id = order.id
            order_reference = order.order_reference
            fulfillment = order.fulfillment
            delivery_address = order.delivery_address
            delivery_fee = order.delivery_fee
    except (StockError, InvalidOperation) as error:
        return json({"detail": str(error)}, status=409)

    if not settings.stripe_secret_key:
        await complete_without_stripe(order_id)
        return json({"order_id": order_id, "order_reference": order_reference, "checkout_url": ""}, status=201)

    try:
        stripe_session = await create_checkout(
            order_id,
            success_url=settings.checkout_success_url,
            cancel_url=settings.checkout_cancel_url,
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {"name": item["name"]},
                        "unit_amount": int(Decimal(item["price"]) * 100),
                    },
                    "quantity": item["quantity"],
                }
                for item in items_context
            ]
            + (
                [
                    {
                        "price_data": {
                            "currency": "usd",
                            "product_data": {"name": "Delivery"},
                            "unit_amount": int(delivery_fee * 100),
                        },
                        "quantity": 1,
                    }
                ]
                if delivery_fee > 0
                else []
            ),
        )
    except Exception:
        logger.exception("Unable to create wholesale Stripe Checkout for order %s", order_id)
        return json({"detail": "Unable to start payment. Please try again."}, status=503)
    return json(
        {"order_id": order_id, "order_reference": order_reference, "checkout_url": stripe_session.url}, status=201
    )


@bp.post("/stripe/webhook/")
async def stripe_webhook(request):
    """Verify and dispatch a signed Stripe webhook event."""
    settings = get_settings()
    if not settings.stripe_secret_key:
        return json({"received": True})

    try:
        event = stripe.Webhook.construct_event(
            request.body,
            request.headers.get("stripe-signature", ""),
            settings.stripe_webhook_secret,
        )
    except Exception:
        return json({"detail": "Invalid webhook."}, status=400)

    if not event.get("id"):
        return json({"detail": "Missing Stripe event ID."}, status=400)
    if event.get("type", "").startswith("invoice."):
        invoice_id = event.get("data", {}).get("object", {}).get("id")
        async with session_scope() as db:
            wedding_id = (
                await db.scalar(select(WeddingInvoice.id).where(WeddingInvoice.stripe_invoice_id == invoice_id))
                if invoice_id
                else None
            )
        outcome = await (apply_wedding_invoice_event(event) if wedding_id else apply_invoice_event(event))
    else:
        outcome = await apply_checkout_event(event)
    if outcome == "review":
        logger.error("Stripe event %s (%s) requires manual reconciliation", event.get("id"), event.get("type"))
        return json({"detail": "Stripe event requires reconciliation."}, status=409)
    return json({"received": True})
