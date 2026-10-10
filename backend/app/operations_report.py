"""Historical stock loss and paid-order item counts; never infer net revenue."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .models import FlowerListing, InventoryMovement, Order


def eastern_window(start: date | None, end: date | None):
    eastern = ZoneInfo("America/New_York")
    lower = datetime.combine(start, time.min, eastern).astimezone(timezone.utc) if start else None
    upper = datetime.combine(end + timedelta(days=1), time.min, eastern).astimezone(timezone.utc) if end else None
    return lower, upper


async def operations_rows(db, start: date | None, end: date | None):
    lower, upper = eastern_window(start, end)
    waste_query = select(InventoryMovement, FlowerListing).join(
        FlowerListing, FlowerListing.id == InventoryMovement.listing_id
    ).where(InventoryMovement.kind == "waste")
    orders_query = select(Order).options(selectinload(Order.items)).where(Order.status.in_(("paid", "refunded")))
    if lower:
        waste_query = waste_query.where(InventoryMovement.created_at >= lower)
        orders_query = orders_query.where(Order.created_at >= lower)
    if upper:
        waste_query = waste_query.where(InventoryMovement.created_at < upper)
        orders_query = orders_query.where(Order.created_at < upper)
    waste = [dict(id=movement.id, listing_id=listing.id, date=movement.created_at, code=listing.listing_code,
                  name=listing.name, units=movement.units, reason=movement.reason,
                  source=movement.source) for movement, listing in
             (await db.execute(waste_query.order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc()))).all()]
    product_totals = defaultdict(lambda: dict(orders=set(), units=0, gross=Decimal("0")))
    channel_totals = defaultdict(lambda: dict(orders=set(), gross=Decimal("0")))
    for order in (await db.scalars(orders_query)).all():
        channel = channel_totals[(order.channel, order.payment_method, order.status)]
        channel["orders"].add(order.id)
        channel["gross"] += sum((item.price_snapshot * item.quantity for item in order.items), Decimal("0")) + order.delivery_fee
        for item in order.items:
            # A removed listing remains visible by its immutable order-item snapshot.
            key = (item.listing_id, item.name_snapshot, order.channel, order.status)
            row = product_totals[key]
            row["orders"].add(order.id)
            row["units"] += item.quantity
            row["gross"] += item.price_snapshot * item.quantity
    products = [dict(listing_id=key[0], name=key[1], channel=key[2], status=key[3],
                     orders=len(value["orders"]), units=value["units"], gross=value["gross"])
                for key, value in sorted(product_totals.items(), key=lambda pair: (pair[0][2], pair[0][1], pair[0][3]))]
    channels = [dict(channel=key[0], payment=key[1], status=key[2],
                     orders=len(value["orders"]), gross=value["gross"])
                for key, value in sorted(channel_totals.items())]
    return waste, products, channels
