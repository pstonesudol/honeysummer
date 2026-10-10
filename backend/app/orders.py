"""Shared order reservation for wholesale and retail checkout.

Inventory is held inside one transaction with ``SELECT … FOR UPDATE`` row
locks so concurrent checkouts cannot oversell, whichever channel they come
from. Wholesale orders belong to an approved florist account; retail orders
are guest checkouts that carry their own contact details.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .models import FlowerListing, InventoryMovement, Order, OrderItem, OrderNotification
from .settings import get_settings


class StockError(ValueError):
    """Raised when a requested item cannot be reserved."""


def listing_available_in_channel(listing: FlowerListing, channel: str) -> bool:
    """Whether a listing may be sold through wholesale or retail checkout."""
    return listing.active and listing.channel in (channel, "both")


async def change_stock(
    session,
    listing: FlowerListing,
    delta: int,
    *,
    kind: str,
    units: int,
    order_id: int | None = None,
    actor_id: int | None = None,
    reason: str = "",
    source: str = "",
) -> None:
    """Write the available balance and its explanation in the same transaction.

    The caller must lock the listing row before entering here. Migration seeds
    preexisting listings; the opening entry also covers newly-created listings.
    """
    existing = await session.scalar(
        select(InventoryMovement.id).where(InventoryMovement.listing_id == listing.id).limit(1)
    )
    if existing is None:
        session.add(
            InventoryMovement(
                listing_id=listing.id,
                kind="opening",
                delta=listing.quantity_available,
                units=listing.quantity_available,
                reason="Initial available balance",
                source="system",
            )
        )
        await session.flush()
    if kind == "opening" and delta == 0 and units == 0:
        return
    if listing.quantity_available + delta < 0:
        raise StockError(f"Not enough {listing.name} available.")
    listing.quantity_available += delta
    session.add(
        InventoryMovement(
            listing_id=listing.id,
            order_id=order_id,
            actor_id=actor_id,
            kind=kind,
            delta=delta,
            units=units,
            reason=reason,
            source=source,
        )
    )


def _cart(items: list[dict]) -> dict[int, int]:
    """Validate, coalesce duplicate lines, and lock listings in stable ID order."""
    if not isinstance(items, list) or not items or len(items) > 100:
        raise StockError("Your cart is empty or too large.")
    cart: dict[int, int] = {}
    try:
        for item in items:
            raw_id, raw_quantity = item["id"], item["quantity"]
            if any(isinstance(value, bool) or not str(value).isdigit() for value in (raw_id, raw_quantity)):
                raise ValueError
            listing_id, quantity = int(raw_id), int(raw_quantity)
            if listing_id < 1 or quantity < 1 or quantity > 9999:
                raise ValueError
            cart[listing_id] = cart.get(listing_id, 0) + quantity
            if cart[listing_id] > 9999:
                raise ValueError
    except TypeError, KeyError, ValueError, AttributeError:
        raise StockError("Enter valid item IDs and quantities.") from None
    return dict(sorted(cart.items()))


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
    checkout_key: str | None = None,
) -> tuple[Order, list[dict]]:
    """Create an order and hold stock for every item.

    Returns the persisted order and an email-friendly context. Raises
    :class:`StockError` if any listing is unknown, unavailable, not sold in the
    requested channel, or short on stock — in which case nothing is committed.
    """
    cart = _cart(items)
    hold_minutes = get_settings().checkout_hold_minutes
    if hold_minutes < 35 or hold_minutes > 1440:
        raise ValueError("CHECKOUT_HOLD_MINUTES must be between 35 and 1440.")
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
        checkout_key=checkout_key,
        hold_expires_at=datetime.now(UTC) + timedelta(minutes=hold_minutes),
    )
    session.add(order)
    await session.flush()
    order_id = order.id
    items_context: list[dict] = []
    delivery_total = Decimal("0")
    per_order_fee = Decimal("0")
    charged_listings: set[int] = set()

    for listing_id, quantity in cart.items():
        listing = (
            await session.execute(select(FlowerListing).where(FlowerListing.id == listing_id).with_for_update())
        ).scalar_one_or_none()
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
        for item in items:
            if int(item["id"]) == listing_id and "price" in item and str(item["price"]) != format(listing.price, ".2f"):
                raise StockError(f"The price of {listing.name} changed. Review your cart before checkout.")
        await change_stock(
            session,
            listing,
            -quantity,
            kind="reserve",
            units=quantity,
            order_id=order_id,
            source="checkout",
        )
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
    for item in sorted(order.items, key=lambda item: item.listing_id):
        listing = await session.scalar(
            select(FlowerListing).where(FlowerListing.id == item.listing_id).with_for_update()
        )
        await change_stock(
            session,
            listing,
            item.quantity,
            kind="release",
            units=item.quantity,
            order_id=order.id,
            source="order",
            reason="Unpaid reservation released",
        )


async def settle_order(session, order: Order) -> None:
    """Turn a hold into a completed sale; availability was already deducted."""
    for item in sorted(order.items, key=lambda item: item.listing_id):
        listing = await session.scalar(
            select(FlowerListing).where(FlowerListing.id == item.listing_id).with_for_update()
        )
        await change_stock(
            session,
            listing,
            0,
            kind="sale",
            units=item.quantity,
            order_id=order.id,
            source="stripe",
            reason="Reservation converted to sale",
        )
    order.status = "paid"
    session.add_all(
        [
            OrderNotification(order_id=order.id, recipient="customer"),
            OrderNotification(order_id=order.id, recipient="farm"),
        ]
    )


async def load_order(session, order_id: int, *, for_update: bool = False) -> Order | None:
    """Load an order with its items and customer, optionally row-locked."""
    query = select(Order).options(selectinload(Order.items), selectinload(Order.customer)).where(Order.id == order_id)
    result = await session.execute(query.with_for_update() if for_update else query)
    return result.scalar_one_or_none()


def items_context(order: Order) -> list[dict]:
    """Build an email-friendly item summary for an order."""
    return [
        {
            "name": item.name_snapshot,
            "price": format(item.price_snapshot, ".2f"),
            "quantity": item.quantity,
        }
        for item in order.items
    ]
