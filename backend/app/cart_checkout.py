"""Opaque checkout capabilities: no PII in status responses or browser storage.

The unique key is committed with the reservation. Retrying an uncertain POST
can only retrieve that attempt, never create another inventory hold.
"""

from uuid import UUID

from sanic.response import json
from sqlalchemy import select

from .db import session_scope
from .models import Order


def checkout_key(data):
    """Validate an optional UUID capability for a checkout attempt."""
    value = data.get("checkout_key")
    if value is None:
        return None  # Backward-compatible callers.
    try:
        return str(UUID(value))
    except ValueError, TypeError, AttributeError:
        raise ValueError("Enter a valid checkout attempt key.") from None


def payload(order):
    """Return payment state without customer or gated product information."""
    return {
        "order_id": order.id,
        "order_reference": order.order_reference,
        "status": order.status,
        "channel": order.channel,
        "checkout_url": order.checkout_url if order.status == "pending" else "",
    }


async def existing_attempt(key, channel, customer_id=None):
    """Retrieve a prior attempt without creating another stock reservation."""
    if not key:
        return None
    async with session_scope() as session:
        order = await session.scalar(select(Order).where(Order.checkout_key == key))
        if order is None:
            return None
        if order.channel != channel or order.customer_id != customer_id:
            return json({"detail": "This checkout attempt belongs to another cart."}, status=403)
        return json(payload(order))
