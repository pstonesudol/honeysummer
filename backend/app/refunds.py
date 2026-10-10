"""Explicit, idempotent payment refunds; stock is never returned automatically."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import func, select

from .db import session_scope
from .models import Order, OrderItem, OrderRefund
from .settings import get_settings


def refund_amount(raw: str) -> int:
    try:
        amount = Decimal(raw)
    except (InvalidOperation, TypeError):
        raise ValueError("Enter a valid refund amount.") from None
    if (not amount.is_finite() or amount < Decimal("0.01") or amount > Decimal("999999.99")
            or amount.as_tuple().exponent < -2):
        raise ValueError("Enter $0.01–$999,999.99 with at most two decimals.")
    return int(amount * 100)


async def issue_refund(order_id: int, form, actor_id: int) -> OrderRefund:
    try:
        key = str(UUID(str(form.get("refund_key", ""))))
    except ValueError:
        raise ValueError("Refresh the order page and try again.") from None
    amount = refund_amount(str(form.get("amount", "")))
    reason = str(form.get("reason", "")).strip()
    reference = str(form.get("reference", "")).strip()
    if not reason or len(reason) > 255:
        raise ValueError("Enter a refund reason (up to 255 characters).")
    if len(reference) > 255:
        raise ValueError("Refund reference is too long.")
    async with session_scope() as db:
        existing = await db.scalar(select(OrderRefund).where(OrderRefund.idempotency_key == key))
        if existing:
            if existing.order_id != order_id or existing.amount_cents != amount or existing.reason != reason:
                raise ValueError("This refund request key was already used for different details.")
            return existing
        order = await db.scalar(select(Order).where(Order.id == order_id).with_for_update())
        if not order or order.status != "paid":
            raise ValueError("Only a paid order can be refunded.")
        if order.payment_method not in ("cash", "external", "stripe_checkout"):
            raise ValueError("This payment requires manual Stripe invoice review before refunding.")
        if order.payment_method == "stripe_checkout":
            if not get_settings().stripe_secret_key or not order.stripe_payment_intent_id:
                raise ValueError("Stripe payment details are unavailable; review in Stripe before refunding.")
        elif not reference or form.get("confirmed") != "on":
            raise ValueError("Confirm the external/cash refund was completed and provide its reference.")
        # Reject all new attempts while a remote request has an uncertain outcome.
        previous = (await db.scalars(select(OrderRefund).where(OrderRefund.order_id == order_id))).all()
        if any(refund.status != "succeeded" for refund in previous):
            raise ValueError("A prior refund needs payment review; do not submit another one.")
        items = (await db.scalars(select(OrderItem).where(OrderItem.order_id == order_id))).all()
        paid_cents = sum(int(item.price_snapshot * item.quantity * 100) for item in items) + int(order.delivery_fee * 100)
        from .models import BouquetProposal
        proposal = await db.scalar(select(BouquetProposal).where(BouquetProposal.order_id == order_id))
        if proposal and proposal.history:
            paid_cents = proposal.history[-1]["draft"]["total_cents"]
        if amount > paid_cents - sum(refund.amount_cents for refund in previous):
            raise ValueError("Refund exceeds the amount not yet refunded.")
        refund = OrderRefund(order_id=order_id, amount_cents=amount, reason=reason,
                             status="issuing" if order.payment_method == "stripe_checkout" else "succeeded",
                             reference=reference, idempotency_key=key, actor_id=actor_id)
        db.add(refund)
        if refund.status == "succeeded":
            if amount == paid_cents - sum(row.amount_cents for row in previous):
                order.status = "refunded"
            order.activity = [*(order.activity or []), dict(action="payment refunded", amount_cents=amount,
                              actor=actor_id, at=datetime.now(timezone.utc).isoformat(), reference=reference)]
        await db.commit()
        refund_id, intent_id = refund.id, order.stripe_payment_intent_id
        if refund.status == "succeeded":
            return refund
    import stripe
    stripe.api_key = get_settings().stripe_secret_key
    try:
        remote = await asyncio.to_thread(stripe.Refund.create, payment_intent=intent_id,
                                         amount=amount, reason="requested_by_customer",
                                         metadata={"order_id": str(order_id), "refund_id": str(refund_id)},
                                         idempotency_key=f"order-refund-{key}")
    except Exception:
        async with session_scope() as db:
            refund = await db.get(OrderRefund, refund_id)
            refund.status = "review"
            await db.commit()
        raise ValueError("Refund outcome is uncertain. Check Stripe before trying again.") from None
    async with session_scope() as db:
        refund = await db.get(OrderRefund, refund_id)
        order = await db.scalar(select(Order).where(Order.id == order_id).with_for_update())
        refund.reference = remote.id
        refund.status = "succeeded" if remote.status == "succeeded" else "review"
        if refund.status == "succeeded":
            completed = await db.scalar(select(func.coalesce(func.sum(OrderRefund.amount_cents), 0)).where(
                OrderRefund.order_id == order_id, OrderRefund.status == "succeeded"))
            if completed >= paid_cents:
                order.status = "refunded"
            order.activity = [*(order.activity or []), dict(action="payment refunded", amount_cents=amount,
                              actor=actor_id, at=datetime.now(timezone.utc).isoformat(), reference=remote.id)]
        await db.commit()
        return refund
