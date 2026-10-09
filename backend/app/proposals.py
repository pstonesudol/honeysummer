"""Bouquet proposal amounts, invoice transitions and paid-order conversion."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from .db import session_scope
from .models import BouquetProposal, FlowerListing, Inquiry, InventoryMovement, Order, OrderItem, OrderNotification, StripeEvent
from .orders import change_stock
from .settings import get_settings


def cents(value: str) -> int:
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError):
        raise ValueError("Enter a valid USD amount.") from None
    if not amount.is_finite() or amount < 0 or amount > 999999 or amount.as_tuple().exponent < -2:
        raise ValueError("Amounts must be nonnegative dollars with at most two decimals.")
    return int(amount * 100)


def validate_draft(data: dict) -> dict:
    title = str(data.get("title", "")).strip()[:160]
    description = str(data.get("description", "")).strip()[:2000]
    terms = str(data.get("terms", "")).strip()[:2000]
    fulfillment = data.get("fulfillment")
    location = str(data.get("location", "")).strip()[:500]
    if not title or not description or not terms or fulfillment not in ("pickup", "delivery") or not location:
        raise ValueError("Title, description, substitution terms, and pickup/delivery details are required.")
    lines = data.get("lines")
    if not isinstance(lines, list) or not 1 <= len(lines) <= 20:
        raise ValueError("Add 1–20 itemized lines.")
    normalized = []
    total = 0
    for line in lines:
        name = str(line.get("name", "")).strip()[:160]
        detail = str(line.get("description", "")).strip()[:500]
        try:
            quantity = int(line.get("quantity", 0))
            listing_id = int(line["listing_id"]) if line.get("listing_id") else None
        except (ValueError, TypeError):
            raise ValueError("Enter valid quantities and listing IDs.") from None
        if not name or quantity < 1 or quantity > 9999 or (listing_id is not None and listing_id < 1):
            raise ValueError("Each line needs a name and a positive quantity.")
        price = cents(str(line.get("price", "")))
        total += price * quantity
        normalized.append(dict(name=name, description=detail, quantity=quantity, unit_cents=price, listing_id=listing_id))
    delivery = cents(str(data.get("delivery", "0"))) if fulfillment == "delivery" else 0
    total += delivery
    if total < 50 or total > 99999999:
        raise ValueError("The total must be between $0.50 and $999,999.99.")
    return dict(title=title, description=description, terms=terms, fulfillment=fulfillment,
                location=location, lines=normalized, delivery_cents=delivery, total_cents=total)


async def send_invoice(proposal_id: int) -> str:
    """Lock out concurrent sends; ambiguous Stripe errors require operator review."""
    import stripe

    settings = get_settings()
    if not settings.stripe_secret_key or not settings.stripe_webhook_secret:
        raise ValueError("Stripe invoices and signed webhooks must be configured before sending.")
    stripe.api_key = settings.stripe_secret_key
    async with session_scope() as db:
        proposal = await db.scalar(select(BouquetProposal).where(BouquetProposal.id == proposal_id).with_for_update())
        if not proposal or proposal.status != "draft":
            raise ValueError("Only a draft can be sent. Review the current invoice in Stripe first.")
        inquiry = await db.get(Inquiry, proposal.inquiry_id)
        draft = proposal.draft
        if not draft or not inquiry.email:
            raise ValueError("Complete the draft and customer email first.")
        for line in draft["lines"]:
            if line["listing_id"] and not await db.get(FlowerListing, line["listing_id"]):
                raise ValueError("A quoted listing no longer exists.")
        version = len(proposal.history) + 1
        proposal.status = "issuing"
        await db.commit()
        email, name = inquiry.email, inquiry.name
    key = f"bouquet-{proposal_id}-v{version}"
    try:
        customer = await asyncio.to_thread(stripe.Customer.create, email=email, name=name, idempotency_key=f"{key}-customer")
        invoice = await asyncio.to_thread(
            stripe.Invoice.create, customer=customer.id, collection_method="send_invoice",
            days_until_due=7, auto_advance=False, pending_invoice_items_behavior="exclude",
            metadata={"proposal_id": str(proposal_id), "version": str(version)},
            description=f"{draft['title']} — {draft['description']}\n{draft['terms']}\n{draft['fulfillment']}: {draft['location']}",
            idempotency_key=f"{key}-invoice",
        )
        for index, line in enumerate(draft["lines"]):
            await asyncio.to_thread(
                stripe.InvoiceItem.create, customer=customer.id, invoice=invoice.id,
                unit_amount_decimal=str(line["unit_cents"]), currency="usd",
                quantity=line["quantity"], description=f"{line['name']} — {line['description']}" if line["description"] else line["name"],
                idempotency_key=f"{key}-line-{index}",
            )
        if draft["delivery_cents"]:
            await asyncio.to_thread(
                stripe.InvoiceItem.create, customer=customer.id, invoice=invoice.id,
                amount=draft["delivery_cents"], currency="usd", description="Delivery / setup",
                idempotency_key=f"{key}-delivery",
            )
        invoice = await asyncio.to_thread(stripe.Invoice.finalize_invoice, invoice.id, idempotency_key=f"{key}-finalize")
        if invoice.total != draft["total_cents"] or invoice.currency != "usd":
            raise ValueError("Stripe invoice total differs from the proposal; inspect and void it in Stripe.")
        invoice = await asyncio.to_thread(stripe.Invoice.send_invoice, invoice.id, idempotency_key=f"{key}-send")
    except Exception:
        async with session_scope() as db:
            current = await db.get(BouquetProposal, proposal_id)
            if current and current.status == "issuing":
                current.status = "review"
                await db.commit()
        raise
    async with session_scope() as db:
        current = await db.get(BouquetProposal, proposal_id)
        current.stripe_customer_id = customer.id
        current.stripe_invoice_id = invoice.id
        current.invoice_url = invoice.hosted_invoice_url or ""
        current.invoice_number = invoice.number or ""
        current.history = [*current.history, dict(version=version, draft=draft, invoice_id=invoice.id,
                                                 sent_at=datetime.now(timezone.utc).isoformat())]
        current.activity = [*(current.activity or []), dict(action="invoice sent", at=datetime.now(timezone.utc).isoformat(), invoice_id=invoice.id)]
        current.status = "sent"
        await db.commit()
    return invoice.id


async def update_sent_invoice(proposal_id: int, action: str) -> None:
    """Only Stripe-confirmed unpaid invoices may be resent, voided or revised."""
    import stripe

    if action not in ("resend", "void", "revise"):
        raise ValueError("Unknown invoice action.")
    if not get_settings().stripe_secret_key:
        raise ValueError("Stripe is not configured.")
    stripe.api_key = get_settings().stripe_secret_key
    async with session_scope() as db:
        proposal = await db.scalar(select(BouquetProposal).where(BouquetProposal.id == proposal_id).with_for_update())
        if not proposal or proposal.status != "sent" or not proposal.stripe_invoice_id:
            raise ValueError("Only an outstanding sent invoice can be changed.")
        invoice_id = proposal.stripe_invoice_id
        # Hold the proposal lock until the remote state and local transition agree.
        remote = await asyncio.to_thread(stripe.Invoice.retrieve, invoice_id)
        if remote.status != "open":
            raise ValueError("Invoice is no longer open in Stripe. Reconcile its payment first.")
        if action == "resend":
            await asyncio.to_thread(stripe.Invoice.send_invoice, invoice_id)
        else:
            remote = await asyncio.to_thread(stripe.Invoice.void_invoice, invoice_id)
            if remote.status != "void":
                raise ValueError("Stripe did not confirm the invoice was voided.")
            proposal.status = "draft" if action == "revise" else "void"
            if action == "revise":
                proposal.stripe_invoice_id = None
                proposal.invoice_url = ""
                proposal.invoice_number = ""
        proposal.activity = [*(proposal.activity or []), dict(action=action, at=datetime.now(timezone.utc).isoformat(), invoice_id=invoice_id)]
        await db.commit()


async def apply_invoice_event(event: dict) -> str:
    """Signed webhook caller supplies an invoice; payment never implies stock existed."""
    from .payments import deliver_notifications

    kind = event.get("type", "")
    if kind not in ("invoice.paid", "invoice.payment_failed", "invoice.voided"):
        return "ignored"
    obj = event.get("data", {}).get("object", {})
    invoice_id = obj.get("id")
    if not invoice_id:
        return "review"
    order_id = None
    async with session_scope() as db:
        proposal = await db.scalar(select(BouquetProposal).where(BouquetProposal.stripe_invoice_id == invoice_id).with_for_update())
        if not proposal:
            return "review"
        proposal_id = proposal.id
        if event.get("id") and await db.scalar(select(StripeEvent.id).where(StripeEvent.event_id == event["id"])):
            return "ignored"
        if kind == "invoice.paid":
            snapshot = proposal.history[-1]["draft"] if proposal.history else None
            if (not snapshot or obj.get("currency") != "usd" or obj.get("total") != snapshot["total_cents"]
                    or obj.get("amount_paid") != snapshot["total_cents"] or obj.get("amount_remaining") != 0
                    or obj.get("paid_out_of_band") or obj.get("status") != "paid"):
                return "review"
            if proposal.order_id:
                return "ignored"
            if proposal.status not in ("sent", "review"):
                return "review"
            inquiry = await db.get(Inquiry, proposal.inquiry_id)
            order = Order(customer_name=inquiry.name, customer_email=inquiry.email, customer_phone=inquiry.phone,
                           channel="retail", status="paid", payment_method="stripe_invoice",
                           payment_reference=invoice_id, fulfillment=snapshot["fulfillment"],
                          pickup_window=snapshot["location"] if snapshot["fulfillment"] == "pickup" else "",
                          delivery_address=snapshot["location"] if snapshot["fulfillment"] == "delivery" else "",
                          delivery_fee=Decimal(snapshot["delivery_cents"]) / 100,
                          notes=f"Custom bouquet proposal #{proposal.id} — {snapshot['title']}")
            db.add(order)
            await db.flush()
            counts: dict[int, int] = {}
            for line in snapshot["lines"]:
                if line["listing_id"]:
                    counts[line["listing_id"]] = counts.get(line["listing_id"], 0) + line["quantity"]
            for listing_id, quantity in sorted(counts.items()):
                listing = await db.scalar(select(FlowerListing).where(FlowerListing.id == listing_id).with_for_update())
                if not listing or listing.quantity_available < quantity:
                    # Paid on Stripe but not booked: leave all balances untouched for owner review.
                    await db.rollback()
                    async with session_scope() as review_db:
                        current = await review_db.get(BouquetProposal, proposal_id)
                        current.status = "stock_review"
                        await review_db.commit()
                    return "review"
                await change_stock(db, listing, -quantity, kind="reserve", units=quantity, order_id=order.id, source="invoice")
                await change_stock(db, listing, 0, kind="sale", units=quantity, order_id=order.id, source="invoice")
            for line in snapshot["lines"]:
                if line["listing_id"]:
                    db.add(OrderItem(order_id=order.id, listing_id=line["listing_id"], name_snapshot=line["name"],
                                     price_snapshot=Decimal(line["unit_cents"]) / 100, quantity=line["quantity"]))
            db.add_all([OrderNotification(order_id=order.id, recipient=recipient) for recipient in ("customer", "farm")])
            proposal.order_id = order.id
            proposal.status = "paid"
            proposal.activity = [*(proposal.activity or []), dict(action="paid", at=datetime.now(timezone.utc).isoformat(), invoice_id=invoice_id)]
            order_id = order.id
        elif proposal.status == "sent":
            if kind == "invoice.voided":
                proposal.status = "void"
            proposal.activity = [*(proposal.activity or []), dict(action="invoice voided" if kind == "invoice.voided" else "payment failed", at=datetime.now(timezone.utc).isoformat(), invoice_id=invoice_id)]
        elif kind == "invoice.voided" and proposal.status == "paid":
            return "review"
        if event.get("id"):
            db.add(StripeEvent(event_id=event["id"], order_id=order_id, event_type=kind, outcome="applied"))
        await db.commit()
    if order_id:
        await deliver_notifications(order_id)
    return "applied"
