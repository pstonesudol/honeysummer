"""Record already-collected off-site payments and sell stock exactly once."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import select

from .models import FlowerListing, Order, OrderItem, OrderNotification
from .orders import StockError, change_stock


def _money(value: str) -> Decimal:
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError):
        raise ValueError("Enter a valid price.") from None
    if not amount.is_finite() or amount < 0 or amount > Decimal("999999.99") or amount.as_tuple().exponent < -2:
        raise ValueError("Prices must be nonnegative dollars with at most two decimal places.")
    return amount


def validate_manual(form) -> dict:
    name = str(form.get("customer_name", "")).strip()
    email = str(form.get("customer_email", "")).strip().lower()
    method = str(form.get("payment_method", ""))
    reference = str(form.get("payment_reference", "")).strip()
    fulfillment = str(form.get("fulfillment", ""))
    try:
        key = str(UUID(str(form.get("manual_key", ""))))
    except ValueError:
        raise ValueError("Form expired. Reload and try again.") from None
    if len(name) < 2 or len(name) > 200 or "@" not in email or len(email) > 254:
        raise ValueError("Enter a customer name and valid email address.")
    if method not in ("cash", "external") or (method == "external" and not reference) or len(reference) > 255:
        raise ValueError("Choose cash or provide an external payment reference.")
    if form.get("payment_confirmed") != "on":
        raise ValueError("Confirm the payment was collected before recording a paid order.")
    collected = _money(str(form.get("amount_collected", "")))
    if fulfillment not in ("pickup", "delivery") or (fulfillment == "delivery" and not str(form.get("delivery_address", "")).strip()):
        raise ValueError("Choose pickup or provide a delivery address.")
    lines = []
    for index in range(1, 6):
        listing_id = str(form.get(f"listing_{index}", "")).strip()
        custom_name = str(form.get(f"name_{index}", "")).strip()
        if not listing_id and not custom_name:
            continue
        try:
            quantity = int(str(form.get(f"quantity_{index}", "")))
            listing = int(listing_id) if listing_id else None
        except ValueError:
            raise ValueError("Enter valid listing IDs and quantities.") from None
        if not 1 <= quantity <= 9999 or (listing is not None and listing < 1):
            raise ValueError("Quantities must be between 1 and 9999.")
        if listing is None and (not 1 <= len(custom_name) <= 160):
            raise ValueError("Name each custom arrangement (up to 160 characters).")
        lines.append(dict(listing_id=listing, name=custom_name, quantity=quantity,
                          price=_money(str(form.get(f"price_{index}", ""))) if listing is None else None))
    if not lines:
        raise ValueError("Add at least one catalogue item or custom arrangement.")
    for field, maximum in (("customer_phone", 40), ("pickup_window", 200), ("delivery_address", 1000), ("notes", 4000)):
        if len(str(form.get(field, ""))) > maximum:
            raise ValueError(f"{field.replace('_', ' ').capitalize()} is too long.")
    return dict(key=key, name=name, email=email, method=method, reference=reference, collected=collected,
                fulfillment=fulfillment, lines=lines)


async def create_manual_order(db, form, actor_id: int) -> Order:
    """Caller commits; row locks and journal entries share that transaction."""
    data = validate_manual(form)
    previous = await db.scalar(select(Order).where(Order.manual_key == data["key"]))
    if previous:
        return previous
    order = Order(
        manual_key=data["key"], customer_name=data["name"], customer_email=data["email"],
        customer_phone=str(form.get("customer_phone", "")).strip(), channel="retail",
        fulfillment=data["fulfillment"], pickup_window=str(form.get("pickup_window", "")).strip(),
        delivery_address=str(form.get("delivery_address", "")).strip(),
        notes=str(form.get("notes", "")).strip(), status="paid", payment_method=data["method"],
        payment_reference=data["reference"], delivery_fee=Decimal("0"),
        activity=[dict(action="manual payment recorded", actor=actor_id, method=data["method"], reference=data["reference"])],
    )
    db.add(order)
    await db.flush()
    counts: dict[int, int] = {}
    for line in data["lines"]:
        if line["listing_id"]:
            counts[line["listing_id"]] = counts.get(line["listing_id"], 0) + line["quantity"]
    listings = {}
    delivery = Decimal("0")
    per_order_fee = Decimal("0")
    for listing_id, quantity in sorted(counts.items()):
        listing = await db.scalar(select(FlowerListing).where(FlowerListing.id == listing_id).with_for_update())
        if not listing or listing.quantity_available < quantity:
            raise StockError("A catalogue item has insufficient stock.")
        listings[listing_id] = listing
        if data["fulfillment"] == "delivery":
            fee = listing.delivery_fee or Decimal("0")
            if listing.delivery_fee_mode == "per_unit":
                delivery += fee * quantity
            elif listing.delivery_fee_mode == "per_order":
                per_order_fee = max(per_order_fee, fee)
            else:
                delivery += fee
    order.delivery_fee = delivery + per_order_fee
    total = order.delivery_fee + sum(
        (listings[line["listing_id"]].price if line["listing_id"] else line["price"]) * line["quantity"]
        for line in data["lines"]
    )
    if total != data["collected"]:
        raise ValueError(f"Collected amount must equal the order total (${total:.2f}, including delivery).")
    for listing_id, quantity in sorted(counts.items()):
        listing = listings[listing_id]
        await change_stock(db, listing, -quantity, kind="market_sale", units=quantity,
                           order_id=order.id, actor_id=actor_id, source="manual_order",
                           reason=f"{data['method']} payment: {data['reference'] or 'cash'}")
    for line in data["lines"]:
        listing = listings.get(line["listing_id"])
        db.add(OrderItem(order_id=order.id, listing_id=listing.id if listing else None,
                         name_snapshot=listing.name if listing else line["name"],
                         price_snapshot=listing.price if listing else line["price"],
                         quantity=line["quantity"]))
    db.add_all([OrderNotification(order_id=order.id, recipient=recipient) for recipient in ("customer", "farm")])
    await db.commit()
    return order
