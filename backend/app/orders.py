"""Shared order reservation for wholesale and retail checkout.

Inventory is held inside one transaction with ``SELECT … FOR UPDATE`` row
locks so concurrent checkouts cannot oversell, whichever channel they come
from. Wholesale orders belong to an approved florist account; retail orders
are guest checkouts that carry their own contact details.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from .models import FlowerListing, Order, OrderItem


class StockError(ValueError):
    """Raised when a requested item cannot be reserved."""


def listing_available_in_channel(listing: FlowerListing, channel: str) -> bool:
    """Whether a listing may be sold through wholesale or retail checkout."""
    return listing.active and listing.channel in (channel, "both")


async def reserve_order(
    session,
    *,
    items: list[dict],
    channel: str,
    customer_id: int | None = None,
    customer_name: str = "",
    customer_email: str = "",
    customer_phone: str = "",
    fulfillment: str = "pickup",
    pickup_window: str = "",
    delivery_address: str = "",
    notes: str = "",
) -> tuple[Order, list[dict]]:
    """Create an order and hold stock for every item.

    Returns the persisted order and an email-friendly context. Raises
    :class:`StockError` if any listing is unknown, unavailable, not sold in the
    requested channel, or short on stock — in which case nothing is committed.
    """
    order = Order(
        customer_id=customer_id,
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone=customer_phone,
        channel=channel,
        fulfillment=fulfillment,
        delivery_fee=Decimal("0"),
        pickup_window=pickup_window,
        delivery_address=delivery_address,
        notes=notes,
    )
    session.add(order)
    await session.flush()
    order_id = order.id
    items_context: list[dict] = []
    delivery_total = Decimal("0")
    per_order_fee = Decimal("0")
    charged_listings: set[int] = set()

    for requested in items:
        listing = (
            await session.execute(
                select(FlowerListing)
                .where(FlowerListing.id == int(requested["id"]))
                .with_for_update()
            )
        ).scalar_one_or_none()
        quantity = int(requested.get("quantity", 0))
        if (
            listing is None
            or not listing_available_in_channel(listing, channel)
            or not listing.available
            or quantity < 1
            or listing.quantity_available < quantity
        ):
            raise StockError(
                f"Not enough {listing.name} available."
                if listing is not None
                else "That flower is no longer available."
            )
        listing.quantity_available -= quantity
        if fulfillment == "delivery":
            fee = listing.delivery_fee or Decimal("0")
            if listing.delivery_fee_mode == "per_unit":
                delivery_total += fee * quantity
            elif listing.delivery_fee_mode == "per_order":
                per_order_fee = max(per_order_fee, fee)
            elif listing.id not in charged_listings:
                delivery_total += fee
            charged_listings.add(listing.id)
        session.add(
            OrderItem(
                order_id=order_id,
                listing_id=listing.id,
                name_snapshot=listing.name,
                price_snapshot=listing.price,
                quantity=quantity,
            )
        )
        items_context.append(
            {
                "name": listing.name,
                "price": format(listing.price, ".2f"),
                "quantity": quantity,
                "variety": listing.variety,
                "color": listing.color,
                "stem_notes": listing.stem_notes,
                "photo": listing.photo,
            }
        )

    if fulfillment == "delivery":
        order.delivery_fee = delivery_total + per_order_fee
    await session.commit()
    return order, items_context


async def release_order(session, order: Order) -> None:
    """Return every held item on an order back to availability."""
    for item in order.items:
        await session.execute(
            update(FlowerListing)
            .where(FlowerListing.id == item.listing_id)
            .values(quantity_available=FlowerListing.quantity_available + item.quantity)
        )


async def load_order(session, order_id: int) -> Order | None:
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.customer))
        .where(Order.id == order_id)
    )
    return result.scalar_one_or_none()


def items_context(order: Order) -> list[dict]:
    return [
        {
            "name": item.name_snapshot,
            "price": format(item.price_snapshot, ".2f"),
            "quantity": item.quantity,
        }
        for item in order.items
    ]
