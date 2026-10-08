"""Wholesale checkout and the Stripe webhook.

Inventory is held inside a transaction with row locks so concurrent checkouts
cannot oversell, mirroring the original Django implementation. Retail guest
checkout shares this machinery through :mod:`app.orders`.
"""

from decimal import Decimal, InvalidOperation

from sanic import Blueprint
from sanic.response import json
from sqlalchemy import update

from ..auth import get_current_user
from ..db import session_scope
from ..emails import send_order_emails
from ..models import Order
from ..orders import (
    StockError,
    items_context as _items_context,
    load_order as _load_order,
    release_order as _release_order,
    reserve_order,
)
from ..settings import get_settings

bp = Blueprint("checkout", url_prefix="/api")


@bp.post("/checkout/")
async def checkout(request):
    user = await get_current_user(request)
    if user is None:
        return json(
            {"detail": "Authentication credentials were not provided."}, status=403
        )
    profile = user.profile
    if profile is None or not profile.approved:
        return json({"detail": "Wholesale approval is required."}, status=403)

    data = request.json or {}
    items = data.get("items", [])
    if not items:
        return json({"detail": "Your cart is empty."}, status=400)

    try:
        async with session_scope() as session:
            order, items_context = await reserve_order(
                session,
                items=items,
                channel="wholesale",
                customer_id=user.id,
                customer_email=user.email,
                fulfillment=str(data.get("fulfillment", "pickup")),
                delivery_fee=data.get("delivery_fee") or 0,
                pickup_window=str(data.get("pickup_window", "")),
                delivery_address=str(data.get("delivery_address", "")),
            )
            order_id = order.id
            fulfillment = order.fulfillment
            pickup_window = order.pickup_window
            delivery_address = order.delivery_address
    except (StockError, InvalidOperation) as error:
        return json({"detail": str(error)}, status=409)

    settings = get_settings()
    customer_email = user.email

    if not settings.stripe_secret_key:
        async with session_scope() as session:
            await session.execute(
                update(Order).where(Order.id == order_id).values(status="paid")
            )
            await session.commit()
        send_order_emails(
            order_id=order_id,
            channel="wholesale",
            fulfillment=fulfillment,
            pickup_window=pickup_window,
            delivery_address=delivery_address,
            customer_email=customer_email,
            items=items_context,
        )
        return json({"order_id": order_id, "checkout_url": ""}, status=201)

    import stripe

    stripe.api_key = settings.stripe_secret_key
    stripe_session = stripe.checkout.Session.create(
        mode="payment",
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
        ],
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


@bp.post("/stripe/webhook/")
async def stripe_webhook(request):
    settings = get_settings()
    if not settings.stripe_secret_key:
        return json({"received": True})

    import stripe

    try:
        event = stripe.Webhook.construct_event(
            request.body,
            request.headers.get("stripe-signature", ""),
            settings.stripe_webhook_secret,
        )
    except Exception:
        return json({"detail": "Invalid webhook."}, status=400)

    order_id = event["data"]["object"].get("metadata", {}).get("order_id")
    if not order_id:
        return json({"received": True})

    async with session_scope() as session:
        order = await _load_order(session, int(order_id))
        if order is None:
            return json({"received": True})

        if event["type"] == "checkout.session.completed":
            order.status = "paid"
            await session.commit()
            send_order_emails(
                order_id=order.id,
                channel=order.channel,
                fulfillment=order.fulfillment,
                pickup_window=order.pickup_window,
                delivery_address=order.delivery_address,
                customer_email=(
                    order.customer.email if order.customer else order.customer_email
                ),
                items=_items_context(order),
            )
        elif event["type"] == "checkout.session.expired":
            await _release_order(session, order)
            order.status = "expired"
            await session.commit()

    return json({"received": True})
