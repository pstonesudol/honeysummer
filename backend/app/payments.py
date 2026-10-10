"""Checkout creation and idempotent, order-locked Stripe payment transitions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import stripe
from sqlalchemy import func, select

from .db import session_scope
from .emails import send_order_emails
from .models import (
    BouquetProposal,
    FlowerListing,
    InventoryMovement,
    Order,
    OrderItem,
    OrderNotification,
    OrderRefund,
    StripeEvent,
)
from .orders import items_context, load_order, release_order, settle_order
from .settings import get_settings


def expected_cents(order: Order) -> int:
    """Return the order total in cents from its items and delivery fee."""
    return int(
        (sum((item.price_snapshot * item.quantity for item in order.items), Decimal("0")) + order.delivery_fee) * 100
    )


async def create_checkout(
    order_id: int, *, line_items: list[dict], success_url: str, cancel_url: str, customer_email: str | None = None
):
    """Create a Stripe Checkout session for a pending order."""

    stripe.api_key = get_settings().stripe_secret_key
    async with session_scope() as db:
        order = await load_order(db, order_id)
    params = dict(
        mode="payment",
        success_url=success_url,
        cancel_url=cancel_url,
        line_items=line_items,
        metadata={"order_id": str(order_id)},
        expires_at=int(order.hold_expires_at.timestamp()),
    )
    if customer_email:
        params["customer_email"] = customer_email
    try:
        checkout = await asyncio.to_thread(
            stripe.checkout.Session.create, **params, idempotency_key=f"honey-order-{order_id}"
        )
    except Exception:
        # No Checkout URL was returned to the buyer. Release the inaccessible hold.
        async with session_scope() as db:
            current = await load_order(db, order_id, for_update=True)
            if current and current.status == "pending" and not current.stripe_session_id:
                await release_order(db, current)
                current.status = "expired"
                await db.commit()
        raise
    try:
        async with session_scope() as db:
            current = await load_order(db, order_id, for_update=True)
            if current.status != "pending":
                raise RuntimeError("The reservation is no longer available.")
            current.stripe_session_id = checkout.id
            if isinstance(getattr(checkout, "expires_at", None), (int, float)):
                current.hold_expires_at = datetime.fromtimestamp(checkout.expires_at, UTC)
            await db.commit()
    except Exception:
        # Keep the hold if Stripe could not confirm expiration; the reconciler
        # will inspect the session instead of selling its stock twice.
        try:
            expired = await asyncio.to_thread(stripe.checkout.Session.expire, checkout.id)
        except Exception:
            pass
        else:
            if getattr(expired, "status", None) == "expired":
                async with session_scope() as db:
                    current = await load_order(db, order_id, for_update=True)
                    if current and current.status == "pending":
                        await release_order(db, current)
                        current.status = "expired"
                        await db.commit()
        raise
    return checkout


async def complete_without_stripe(order_id: int) -> None:
    """Explicit local-development mode (never use with live payments)."""
    async with session_scope() as db:
        order = await load_order(db, order_id, for_update=True)
        if order and order.status == "pending":
            await settle_order(db, order)
            await db.commit()
    await deliver_notifications(order_id)


async def deliver_notifications(order_id: int) -> None:
    """At-least-once outbox: a failed delivery stays queued for the next sweep."""
    for recipient in ("customer", "farm"):
        async with session_scope() as db:
            notification = await db.scalar(
                select(OrderNotification)
                .where(
                    OrderNotification.order_id == order_id,
                    OrderNotification.recipient == recipient,
                    OrderNotification.sent_at.is_(None),
                )
                .with_for_update()
            )
            if not notification:
                continue
            order = await load_order(db, order_id)
            proposal = await db.scalar(select(BouquetProposal).where(BouquetProposal.order_id == order_id))
            context = items_context(order)
            if proposal and proposal.history:
                context = [
                    dict(name=line["name"], price=f"{Decimal(line['unit_cents']) / 100:.2f}", quantity=line["quantity"])
                    for line in proposal.history[-1]["draft"]["lines"]
                ]
            notification.attempts += 1
            try:
                send_order_emails(
                    order_id=order.id,
                    order_reference=order.order_reference,
                    channel=order.channel,
                    fulfillment=order.fulfillment,
                    pickup_window=order.pickup_window,
                    delivery_address=order.delivery_address,
                    customer_email=order.customer.email if order.customer else order.customer_email,
                    items=context,
                    delivery_fee=order.delivery_fee,
                    recipient=recipient,
                    raise_errors=True,
                )
            except Exception:
                await db.commit()
            else:
                notification.sent_at = datetime.now(UTC)
                await db.commit()


async def expire_checkout(order_id: int) -> str:
    """Confirm the hosted session is no longer payable before releasing stock."""

    async with session_scope() as db:
        order = await load_order(db, order_id)
    if not order or order.status != "pending":
        return "review"
    if not order.stripe_session_id:
        return "safe" if not get_settings().stripe_secret_key else "review"
    if not get_settings().stripe_secret_key:
        return "review"
    stripe.api_key = get_settings().stripe_secret_key
    try:
        remote = await asyncio.to_thread(stripe.checkout.Session.retrieve, order.stripe_session_id)
        if remote.status == "open":
            remote = await asyncio.to_thread(stripe.checkout.Session.expire, order.stripe_session_id)
        return "safe" if remote.status == "expired" else "review"
    except Exception:
        return "review"


async def apply_checkout_event(event: dict) -> str:
    """Return applied/ignored/review; never treat the redirect as proof of payment."""
    event_type = event.get("type", "")
    obj = event.get("data", {}).get("object", {})
    event_id = event.get("id")
    if event_type == "charge.refunded":
        intent = obj.get("payment_intent")
        amount_refunded, amount_paid = obj.get("amount_refunded"), obj.get("amount")
        if (
            not intent
            or obj.get("currency") != "usd"
            or not isinstance(amount_paid, int)
            or not isinstance(amount_refunded, int)
            or not 0 < amount_refunded <= amount_paid
        ):
            return "review"
        async with session_scope() as db:
            order_id = await db.scalar(select(Order.id).where(Order.stripe_payment_intent_id == intent))
            if order_id is None:
                return "review"
            order = await load_order(db, order_id, for_update=True)
            if event_id and await db.scalar(select(StripeEvent.id).where(StripeEvent.event_id == event_id)):
                return "ignored"
            proposal = await db.scalar(select(BouquetProposal).where(BouquetProposal.order_id == order_id))
            total = (
                proposal.history[-1]["draft"]["total_cents"] if proposal and proposal.history else expected_cents(order)
            )
            if order.status not in ("paid", "refunded") or amount_paid != total:
                return "review"
            refunds = (await db.scalars(select(OrderRefund).where(OrderRefund.order_id == order_id))).all()
            recorded = sum(row.amount_cents for row in refunds if row.status == "succeeded")
            if order.status == "refunded" and recorded == total and amount_refunded <= total:
                if event_id:
                    db.add(StripeEvent(event_id=event_id, order_id=order.id, event_type=event_type, outcome="ignored"))
                    await db.commit()
                return "ignored"
            if recorded > amount_refunded or any(row.status == "review" for row in refunds):
                return "review"
            if issuing := next((row for row in refunds if row.status == "issuing"), None):
                if recorded + issuing.amount_cents != amount_refunded:
                    return "review"
                issuing.status = "succeeded"
            elif amount_refunded < total and recorded != amount_refunded:
                # Unknown partial refunds need operator review rather than an
                # invented allocation to a local refund request.
                return "review"
            elif recorded < amount_refunded:
                db.add(
                    OrderRefund(
                        order_id=order_id,
                        amount_cents=amount_refunded - recorded,
                        status="succeeded",
                        reason="Full refund verified from Stripe webhook",
                        reference=str(obj.get("id", "")),
                        idempotency_key=str(uuid4()),
                    )
                )
            if amount_refunded == total and order.status != "refunded":
                order.status = "refunded"
                for item in order.items:
                    if item.listing_id is None:
                        continue  # Custom services have no inventory journal.
                    db.add(
                        InventoryMovement(
                            listing_id=item.listing_id,
                            order_id=order.id,
                            kind="refund",
                            delta=0,
                            units=item.quantity,
                            reason="Full refund; no automatic restock",
                            source="stripe",
                        )
                    )
            if event_id:
                db.add(StripeEvent(event_id=event_id, order_id=order.id, event_type=event_type, outcome="applied"))
            await db.commit()
            return "applied"
    if event_type not in {
        "checkout.session.completed",
        "checkout.session.expired",
        "checkout.session.async_payment_succeeded",
        "checkout.session.async_payment_failed",
    }:
        return "ignored"
    try:
        order_id = int(obj.get("metadata", {}).get("order_id", ""))
    except ValueError, TypeError:
        return "ignored"
    async with session_scope() as db:
        order = await load_order(db, order_id, for_update=True)
        if not order or not obj.get("id") or order.stripe_session_id != obj["id"]:
            return "review"
        if event_id and await db.scalar(select(StripeEvent.id).where(StripeEvent.event_id == event_id)):
            return "ignored"
        paid = event_type == "checkout.session.async_payment_succeeded" or (
            event_type == "checkout.session.completed" and obj.get("payment_status") == "paid"
        )
        outcome = "ignored"
        if paid:
            if obj.get("currency") != "usd" or obj.get("amount_total") != expected_cents(order):
                outcome = "review"
            elif order.status == "pending":
                await settle_order(db, order)
                order.stripe_payment_intent_id = obj.get("payment_intent")
                outcome = "applied"
            elif order.status not in ("paid", "refunded"):
                outcome = "review"
        elif event_type in ("checkout.session.expired", "checkout.session.async_payment_failed"):
            if order.status == "pending":
                await release_order(db, order)
                order.status = "expired"
                outcome = "applied"
            elif order.status not in ("expired", "cancelled"):
                outcome = "review"
        # Completed + unpaid: wait for async success/failure; never release early.
        if event_id and outcome != "review":
            db.add(StripeEvent(event_id=event_id, order_id=order.id, event_type=event_type, outcome=outcome))
        await db.commit()
        if paid and outcome == "applied":
            await deliver_notifications(order.id)
        return outcome


async def reconcile(*, apply: bool = False, full: bool = False) -> list[str]:
    """Audit every balance and inspect overdue reservations against Stripe."""
    findings: list[str] = []
    now = datetime.now(UTC)
    async with session_scope() as db:
        listings = (await db.scalars(select(FlowerListing).order_by(FlowerListing.id))).all()
        for listing in listings:
            ledger = await db.scalar(
                select(func.sum(InventoryMovement.delta)).where(InventoryMovement.listing_id == listing.id)
            )
            if ledger is None or ledger != listing.quantity_available:
                findings.append(f"Listing #{listing.id}: available={listing.quantity_available}, ledger={ledger}")
            reserved = await db.scalar(
                select(func.coalesce(func.sum(OrderItem.quantity), 0))
                .join(Order, Order.id == OrderItem.order_id)
                .where(OrderItem.listing_id == listing.id, Order.status == "pending")
            )
            movements = (
                await db.scalars(select(InventoryMovement).where(InventoryMovement.listing_id == listing.id))
            ).all()
            journal_reserved = sum(
                movement.units * (1 if movement.kind in ("reserve", "legacy_hold") else -1)
                for movement in movements
                if movement.kind in ("reserve", "legacy_hold", "release", "sale")
            )
            if reserved != journal_reserved:
                findings.append(f"Listing #{listing.id}: pending units={reserved}, journal holds={journal_reserved}")
        pending_ids = (await db.scalars(select(Order.id).where(Order.status == "pending"))).all()
    for order_id in pending_ids:
        async with session_scope() as db:
            order = await load_order(db, order_id)
            deadline = order.hold_expires_at
            if deadline is not None and deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=UTC)  # SQLite test adapter
            due = deadline is None or deadline <= now
            session_id = order.stripe_session_id
        if not due:
            continue
        if not session_id:
            if get_settings().stripe_secret_key or not get_settings().debug:
                # Session creation may have succeeded before persisting its ID
                # failed, and expiration may have failed too. Without the ID we
                # cannot prove that the Checkout session is unpayable.
                findings.append(f"Order #{order_id}: orphaned pending hold; Stripe session unknown, manual review")
            else:
                findings.append(f"Order #{order_id}: orphaned pending hold")
            if apply and get_settings().debug and not get_settings().stripe_secret_key:
                async with session_scope() as db:
                    current = await load_order(db, order_id, for_update=True)
                    if current and current.status == "pending" and not current.stripe_session_id:
                        await release_order(db, current)
                        current.status = "expired"
                        await db.commit()
            continue
        if not get_settings().stripe_secret_key:
            findings.append(f"Order #{order_id}: Stripe key missing; cannot reconcile")
            continue

        stripe.api_key = get_settings().stripe_secret_key
        try:
            remote = await asyncio.to_thread(stripe.checkout.Session.retrieve, session_id)
        except Exception as exc:
            findings.append(f"Order #{order_id}: Stripe lookup failed: {exc}")
            continue
        if remote.status == "complete" and remote.payment_status == "paid":
            findings.append(f"Order #{order_id}: paid on Stripe but pending locally")
            if apply:
                outcome = await apply_checkout_event({"type": "checkout.session.completed", "data": {"object": remote}})
                if outcome != "applied":
                    findings.append(f"Order #{order_id}: {outcome}; manual review")
        elif remote.status == "expired" or (
            remote.status == "open" and apply and await expire_checkout(order_id) == "safe"
        ):
            findings.append(f"Order #{order_id}: expired or overdue open session")
            if apply:
                async with session_scope() as db:
                    current = await load_order(db, order_id, for_update=True)
                    if current and current.status == "pending" and current.stripe_session_id == session_id:
                        await release_order(db, current)
                        current.status = "expired"
                        await db.commit()
        else:
            findings.append(f"Order #{order_id}: Stripe {remote.status}/{remote.payment_status}; manual review")
    async with session_scope() as db:
        unsent_ids = (
            await db.scalars(select(OrderNotification.order_id).where(OrderNotification.sent_at.is_(None)).distinct())
        ).all()
        paid_query = select(Order.id).where(Order.status == "paid", Order.stripe_session_id.is_not(None))
        if not full:
            paid_query = paid_query.where(Order.created_at >= now - timedelta(days=2))
        paid_ids = (await db.scalars(paid_query)).all()
        invoice_ids = (
            await db.scalars(
                select(BouquetProposal.id).where(
                    BouquetProposal.stripe_invoice_id.is_not(None),
                    BouquetProposal.status.in_(("sent", "review", "stock_review", "paid")),
                )
            )
        ).all()
    for order_id in unsent_ids:
        findings.append(f"Order #{order_id}: unsent confirmation email")
        if apply:
            await deliver_notifications(order_id)
    if get_settings().stripe_secret_key:
        stripe.api_key = get_settings().stripe_secret_key
        # payments <-> proposals is a deliberate import cycle; keep this lazy.
        from .proposals import apply_invoice_event  # noqa: PLC0415

        for proposal_id in invoice_ids:
            async with session_scope() as db:
                proposal = await db.get(BouquetProposal, proposal_id)
                invoice_id, local_status = proposal.stripe_invoice_id, proposal.status
                snapshot = proposal.history[-1]["draft"] if proposal.history else None
            try:
                remote = await asyncio.to_thread(stripe.Invoice.retrieve, invoice_id)
                if snapshot and (remote.currency != "usd" or remote.total != snapshot["total_cents"]):
                    findings.append(f"Proposal #{proposal_id}: Stripe total/currency mismatch; manual review")
                elif remote.status == "paid" and local_status != "paid":
                    findings.append(f"Proposal #{proposal_id}: paid invoice not booked locally")
                    if apply:
                        outcome = await apply_invoice_event({"type": "invoice.paid", "data": {"object": remote}})
                        if outcome != "applied":
                            findings.append(f"Proposal #{proposal_id}: {outcome}; manual review")
                elif local_status == "paid" and remote.status != "paid":
                    findings.append(f"Proposal #{proposal_id}: local payment differs from Stripe; manual review")
                elif remote.status == "void" and local_status == "sent":
                    findings.append(f"Proposal #{proposal_id}: void on Stripe but sent locally")
                    if apply:
                        await apply_invoice_event({"type": "invoice.voided", "data": {"object": remote}})
                elif (
                    remote.status == "open"
                    and local_status == "sent"
                    and remote.due_date
                    and remote.due_date < int(now.timestamp())
                ):
                    findings.append(f"Proposal #{proposal_id}: invoice overdue")
            except Exception as exc:
                findings.append(f"Proposal #{proposal_id}: Stripe invoice lookup failed: {exc}")
        for order_id in paid_ids:
            async with session_scope() as db:
                order = await load_order(db, order_id)
            try:
                remote = await asyncio.to_thread(stripe.checkout.Session.retrieve, order.stripe_session_id)
                if (
                    remote.payment_status != "paid"
                    or remote.currency != "usd"
                    or remote.amount_total != expected_cents(order)
                ):
                    findings.append(f"Order #{order_id}: local total/payment differs from Stripe; manual review")
                    continue
                if order.stripe_payment_intent_id:
                    intent = await asyncio.to_thread(
                        stripe.PaymentIntent.retrieve,
                        order.stripe_payment_intent_id,
                        expand=["latest_charge"],
                    )
                    charge = intent.get("latest_charge")
                    if isinstance(charge, str):
                        charge = await asyncio.to_thread(stripe.Charge.retrieve, charge)
                    if charge and charge.get("amount_refunded", 0):
                        if charge.get("amount_refunded") == charge.get("amount") == expected_cents(order):
                            findings.append(f"Order #{order_id}: fully refunded on Stripe, still paid locally")
                            if apply:
                                await apply_checkout_event({"type": "charge.refunded", "data": {"object": charge}})
                        else:
                            findings.append(f"Order #{order_id}: partial/unequal refund; manual review")
            except Exception as exc:
                findings.append(f"Order #{order_id}: paid-order Stripe lookup failed: {exc}")
    return findings
