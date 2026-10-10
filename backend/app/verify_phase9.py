"""Controlled Stripe TEST-MODE acceptance. Creates only new synthetic records.

Default: report configuration. --apply creates/charges/refunds test invoices;
never run with live credentials, and never uses existing quotes or customers.
"""

import argparse
import asyncio
from datetime import timedelta
from uuid import uuid4

import stripe
from sqlalchemy import select

from .db import session_scope
from .invoice_refunds import import_external_invoice_refund, issue_invoice_refund
from .models import Inquiry, Order, OrderRefund, User, WeddingInvoice, WeddingQuote
from .settings import get_settings
from .weddings import (
    agree_revised_wedding,
    apply_wedding_invoice_event,
    attach_reviewed_wedding_invoice,
    eastern_today,
    revise_wedding_invoice,
    send_wedding_invoice,
    validate_quote,
)


async def verify(*, apply=False):
    """Exercise new synthetic wedding invoices and refunds with test-only credentials."""
    settings = get_settings()
    if not settings.stripe_secret_key.startswith("sk_test_"):
        raise ValueError("Only sk_test_ credentials are allowed.")
    if not apply:
        return ["Test credentials configured. --apply creates new synthetic test invoices, payments and refunds."]
    if not settings.debug:
        raise ValueError("Synthetic verification requires DEBUG=true in a nonproduction environment.")
    stripe.api_key = settings.stripe_secret_key
    async with session_scope() as db:
        actor = await db.scalar(
            select(User.id).where(User.is_admin.is_(True), User.is_active.is_(True)).order_by(User.id)
        )
        if not actor:
            raise ValueError("An existing active operator is required.")
        inquiry = Inquiry(
            kind="wedding", name="Phase 9 synthetic acceptance", email=f"phase9-{uuid4().hex}@example.invalid"
        )
        db.add(inquiry)
        await db.flush()
        form = dict(
            title="Phase 9 TEST ONLY",
            description="Synthetic flowers, no stock",
            terms="Stripe test-mode verification only",
            location="Synthetic test venue",
            payment_mode="deposit",
            deposit="1.00",
            line_ids="1",
            name_1="Test event flowers",
            quantity_1="1",
            price_1="3.00",
        )
        draft, _, _ = validate_quote(form)
        quote = WeddingQuote(inquiry_id=inquiry.id, draft=draft, snapshot={}, payment_mode="deposit", deposit_cents=100)
        db.add(quote)
        await db.commit()
        quote_id = quote.id
    findings = [f"Created synthetic quote #{quote_id}"]
    deposit_id = await send_wedding_invoice(quote_id, "deposit")
    remote = await asyncio.to_thread(stripe.Invoice.retrieve, deposit_id)
    payment_method = await asyncio.to_thread(stripe.PaymentMethod.attach, "pm_card_visa", customer=remote.customer)

    async def pay_and_apply(invoice_id):
        paid = await asyncio.to_thread(
            stripe.Invoice.pay,
            invoice_id,
            payment_method=payment_method.id,
            idempotency_key=f"phase9-test-pay-{invoice_id}",
        )
        event = dict(
            id=f"phase9-test-{invoice_id}",
            type="invoice.paid",
            data={
                "object": {
                    key: paid.get(key)
                    for key in (
                        "id",
                        "currency",
                        "total",
                        "amount_paid",
                        "amount_remaining",
                        "status",
                        "paid_out_of_band",
                    )
                }
            },
        )
        outcome = await apply_wedding_invoice_event(event)
        if outcome != "applied" or await apply_wedding_invoice_event(event) != "ignored":
            raise ValueError(f"Payment transition needs review for {invoice_id}: {outcome}")
        return paid

    await pay_and_apply(deposit_id)
    async with session_scope() as db:
        quote = await db.get(WeddingQuote, quote_id)
        if quote.order_id or quote.status != "deposit_paid":
            raise ValueError("Deposit incorrectly created a paid order.")
        invoice_pk = await db.scalar(select(WeddingInvoice.id).where(WeddingInvoice.stripe_invoice_id == deposit_id))
    refund = await issue_invoice_refund(
        "wedding",
        invoice_pk,
        dict(refund_key=str(uuid4()), amount="0.50", reason="Synthetic partial refund acceptance"),
        actor,
    )
    if refund.status != "succeeded":
        raise ValueError("Test refund needs review; do not retry blindly.")
    await agree_revised_wedding(
        quote_id,
        {
            **form,
            "customer_accepted": "on",
            "acceptance_reference": "Synthetic test acceptance; not a real customer agreement",
            "amendment_due_date": (eastern_today() + timedelta(days=7)).isoformat(),
        },
        actor_id=actor,
    )
    amended_id = await send_wedding_invoice(quote_id, "amended")
    await pay_and_apply(amended_id)
    async with session_scope() as db:
        quote = await db.get(WeddingQuote, quote_id)
        order_id = quote.order_id
        amended_pk = await db.scalar(select(WeddingInvoice.id).where(WeddingInvoice.stripe_invoice_id == amended_id))
        if quote.status != "paid" or not order_id or quote.amendments[-1]["amount_cents"] != 250:
            raise ValueError("Revised final payment did not create the expected paid order.")
    final_refund = await issue_invoice_refund(
        "wedding",
        amended_pk,
        dict(refund_key=str(uuid4()), amount="0.50", reason="Synthetic paid-order refund acceptance"),
        actor,
    )
    external = await asyncio.to_thread(
        stripe.Refund.create,
        payment_intent=final_refund.payment_intent_id,
        amount=50,
        idempotency_key=f"phase9-test-external-{amended_id}",
    )
    await import_external_invoice_refund("wedding", amended_pk, external.id, actor)
    await import_external_invoice_refund("wedding", amended_pk, external.id, actor)
    async with session_scope() as db:
        refunds = (await db.scalars(select(OrderRefund).where(OrderRefund.order_id == order_id))).all()
        order = await db.get(Order, order_id)
        if sum(row.amount_cents for row in refunds) != 100 or order.status != "paid":
            raise ValueError("Refund journal or partial-refund status differs.")
    findings.append(
        f"PASS: deposit {deposit_id}, amended balance {amended_id}, paid order #{order_id}; "
        "partial refunds and idempotent external import verified. No catalogue lines or stock changes."
    )
    async with session_scope() as db:
        inquiry = Inquiry(
            kind="wedding", name="Phase 9 revision acceptance", email=f"phase9-{uuid4().hex}@example.invalid"
        )
        db.add(inquiry)
        await db.flush()
        revision_form = {**form, "payment_mode": "full", "price_1": "1.00"}
        revision_draft, _, _ = validate_quote(revision_form)
        revision_quote = WeddingQuote(inquiry_id=inquiry.id, draft=revision_draft, payment_mode="full")
        db.add(revision_quote)
        await db.commit()
        revision_quote_id = revision_quote.id
    original_id = await send_wedding_invoice(revision_quote_id, "full")
    async with session_scope() as db:
        original_pk = await db.scalar(select(WeddingInvoice.id).where(WeddingInvoice.stripe_invoice_id == original_id))
    await revise_wedding_invoice(revision_quote_id, original_pk, actor_id=actor)
    replacement_id = await send_wedding_invoice(revision_quote_id, "full")
    if replacement_id == original_id:
        raise ValueError("Replacement invoice reused the original Stripe ID.")
    async with session_scope() as db:
        row = await db.scalar(select(WeddingInvoice).where(WeddingInvoice.stripe_invoice_id == replacement_id))
        replacement_pk = row.id
        row.stripe_invoice_id = None
        row.status = "review"
        quote = await db.get(WeddingQuote, revision_quote_id)
        quote.status = "review"
        await db.commit()
    await attach_reviewed_wedding_invoice(revision_quote_id, replacement_pk, replacement_id, actor_id=actor)
    await revise_wedding_invoice(revision_quote_id, replacement_pk, actor_id=actor)
    findings.append(
        f"PASS: synthetic quote #{revision_quote_id}; void/revision {original_id} -> {replacement_id}; "
        "exact unknown-ID recovery verified. Both unpaid test invoices voided."
    )
    findings.append("Payments retrieved from Stripe; signed webhook delivery and owner device checks are separate.")
    return findings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    for line in asyncio.run(verify(apply=args.apply)):
        print(line)
