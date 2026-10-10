"""Guarded refunds of individual paid Stripe invoice payments."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import stripe
from sqlalchemy import select

from .db import session_scope
from .models import BouquetProposal, Inquiry, InvoiceRefund, Order, OrderRefund, WeddingInvoice, WeddingQuote
from .refunds import refund_amount
from .settings import get_settings


async def close_fully_refunded_quote(kind: str, pk: int, actor_id: int) -> None:
    """Owner cancellation only after every Stripe-paid invoice was fully refunded."""

    if kind not in ("wedding", "bouquet"):
        raise ValueError("Unknown quote type.")
    async with session_scope() as db:
        model = WeddingQuote if kind == "wedding" else BouquetProposal
        quote = await db.scalar(select(model).where(model.id == pk).with_for_update())
        if not quote or quote.status != "review":
            raise ValueError("Only a paused, review-state quote can be closed after refunds.")
        if kind == "wedding":
            invoices = (await db.scalars(select(WeddingInvoice).where(WeddingInvoice.quote_id == pk))).all()
            if any(invoice.status not in ("paid", "void") for invoice in invoices):
                raise ValueError("An outstanding or uncertain invoice still needs Stripe review.")
            paid = [invoice for invoice in invoices if invoice.status == "paid"]
            refunds = (
                (
                    await db.scalars(
                        select(InvoiceRefund).where(
                            InvoiceRefund.wedding_invoice_id.in_([invoice.id for invoice in paid])
                        )
                    )
                ).all()
                if paid
                else []
            )
            if (
                not paid
                or any(item.status != "succeeded" for item in refunds)
                or sum(item.amount_cents for item in refunds) != sum(invoice.amount_cents for invoice in paid)
            ):
                raise ValueError("Every paid invoice must have a confirmed full refund before closing.")
        else:
            refunds = (await db.scalars(select(InvoiceRefund).where(InvoiceRefund.proposal_id == pk))).all()
            if (
                not quote.order_id
                or any(item.status != "succeeded" for item in refunds)
                or sum(item.amount_cents for item in refunds) != quote.history[-1]["draft"]["total_cents"]
            ):
                raise ValueError("The bouquet invoice must be fully refunded before closing.")
        if quote.order_id:
            order = await db.scalar(select(Order).where(Order.id == quote.order_id).with_for_update())
            if order.status != "refunded":
                raise ValueError("The paid order still needs payment review.")
        quote.status = "cancelled"
        quote.activity = [
            *(quote.activity or []),
            dict(action="fully refunded quote closed", actor=actor_id, at=datetime.now(UTC).isoformat()),
        ]
        inquiry = await db.get(Inquiry, quote.inquiry_id)
        inquiry.stage = "closed"
        await db.commit()


async def _complete_refund(db, row: InvoiceRefund, remote_id: str) -> None:
    """Record confirmed payment exactly once; stock remains a separate workflow."""
    if row.status == "succeeded":
        return
    row.status = "succeeded"
    row.stripe_refund_id = remote_id
    kind = "wedding" if row.wedding_invoice_id is not None else "bouquet"
    owner_model = WeddingQuote if kind == "wedding" else BouquetProposal
    if kind == "wedding":
        invoice = await db.get(WeddingInvoice, row.wedding_invoice_id)
        owner_id = invoice.quote_id
        invoice_id = invoice.stripe_invoice_id
    else:
        owner_id = row.proposal_id
        owner = await db.get(BouquetProposal, owner_id)
        invoice_id = owner.stripe_invoice_id
    owner = await db.scalar(select(owner_model).where(owner_model.id == owner_id).with_for_update())
    owner.activity = [
        *(owner.activity or []),
        dict(
            action="invoice payment refunded; review required",
            invoice_id=invoice_id,
            amount_cents=row.amount_cents,
            refund_id=remote_id,
            actor=row.actor_id,
            at=datetime.now(UTC).isoformat(),
        ),
    ]
    if owner.order_id:
        order = await db.scalar(select(Order).where(Order.id == owner.order_id).with_for_update())
        if await db.scalar(select(OrderRefund.id).where(OrderRefund.idempotency_key == row.idempotency_key)):
            raise ValueError("This refund is already in the order ledger; review before continuing.")
        existing = (
            await db.scalars(
                select(OrderRefund).where(OrderRefund.order_id == order.id, OrderRefund.status == "succeeded")
            )
        ).all()
        total = (
            owner.amendments[-1]["draft"]["total_cents"]
            if kind == "wedding" and owner.amendments
            else owner.snapshot["total_cents"]
            if kind == "wedding"
            else owner.history[-1]["draft"]["total_cents"]
        )
        refunded = row.amount_cents + sum(item.amount_cents for item in existing)
        if refunded > total:
            raise ValueError("Refund exceeds the paid order total; review the order ledger.")
        db.add(
            OrderRefund(
                order_id=order.id,
                amount_cents=row.amount_cents,
                status="succeeded",
                reference=remote_id,
                reason=row.reason,
                idempotency_key=row.idempotency_key,
                actor_id=row.actor_id,
            )
        )
        if refunded == total:
            order.status = "refunded"
        order.activity = [
            *(order.activity or []),
            dict(
                action="invoice payment refunded",
                amount_cents=row.amount_cents,
                reference=remote_id,
                actor=row.actor_id,
                at=datetime.now(UTC).isoformat(),
            ),
        ]


async def reconcile_invoice_refund(refund_id: int) -> str:
    """Resolve a recorded Stripe refund ID; missing IDs remain manual-review only."""

    if not get_settings().stripe_secret_key:
        raise ValueError("Stripe is not configured.")
    stripe.api_key = get_settings().stripe_secret_key
    async with session_scope() as db:
        row = await db.scalar(select(InvoiceRefund).where(InvoiceRefund.id == refund_id).with_for_update())
        if not row or not row.stripe_refund_id:
            raise ValueError("No Stripe refund ID is stored. Verify the outcome in Stripe manually.")
        if row.status == "succeeded":
            return "succeeded"
        try:
            remote = await asyncio.to_thread(stripe.Refund.retrieve, row.stripe_refund_id)
        except Exception:
            raise ValueError("Stripe refund status could not be verified.") from None
        if (
            remote.id != row.stripe_refund_id
            or remote.payment_intent != row.payment_intent_id
            or remote.amount != row.amount_cents
            or remote.currency != "usd"
            or (remote.get("metadata") or {}).get("invoice_refund_id") != str(row.id)
        ):
            raise ValueError("Stripe refund does not match this invoice payment; review manually.")
        if remote.status != "succeeded":
            return "review"
        await _complete_refund(db, row, remote.id)
        await db.commit()
        return "succeeded"


async def issue_invoice_refund(kind: str, pk: int, form, actor_id: int) -> InvoiceRefund:
    """Verify a paid Stripe invoice and issue an idempotent refund against it."""

    if kind not in ("wedding", "bouquet"):
        raise ValueError("Unknown invoice type.")
    try:
        key = str(UUID(str(form.get("refund_key", ""))))
    except ValueError:
        raise ValueError("Refresh the invoice page and try again.") from None
    amount = refund_amount(str(form.get("amount", "")))
    reason = str(form.get("reason", "")).strip()
    if not 1 <= len(reason) <= 255:
        raise ValueError("Enter a refund reason (up to 255 characters).")
    if not get_settings().stripe_secret_key:
        raise ValueError("Stripe is not configured.")
    stripe.api_key = get_settings().stripe_secret_key
    source = "wedding_invoice_id" if kind == "wedding" else "proposal_id"
    async with session_scope() as db:
        existing = await db.scalar(select(InvoiceRefund).where(InvoiceRefund.idempotency_key == key))
        if existing:
            if getattr(existing, source) != pk or existing.amount_cents != amount or existing.reason != reason:
                raise ValueError("This refund key was already used for a different payment.")
            return existing
        if kind == "wedding":
            invoice = await db.scalar(select(WeddingInvoice).where(WeddingInvoice.id == pk).with_for_update())
            if not invoice or invoice.status != "paid" or not invoice.stripe_invoice_id:
                raise ValueError("Only a verified paid wedding invoice can be refunded.")
            owner = await db.scalar(select(WeddingQuote).where(WeddingQuote.id == invoice.quote_id).with_for_update())
            remote_id, paid_cents = invoice.stripe_invoice_id, invoice.amount_cents
        else:
            owner = await db.scalar(select(BouquetProposal).where(BouquetProposal.id == pk).with_for_update())
            if not owner or not owner.stripe_invoice_id or not owner.order_id:
                raise ValueError("Only a verified paid bouquet invoice can be refunded.")
            remote_id, paid_cents = owner.stripe_invoice_id, owner.history[-1]["draft"]["total_cents"]
        previous = (await db.scalars(select(InvoiceRefund).where(getattr(InvoiceRefund, source) == pk))).all()
        if any(item.status != "succeeded" for item in previous):
            raise ValueError("An earlier refund needs Stripe review. Do not retry it.")
        if owner.status not in (
            ("deposit_paid", "installment_paid", "paid") if kind == "wedding" else ("paid",)
        ) and not (owner.status == "review" and previous and all(item.status == "succeeded" for item in previous)):
            raise ValueError("Review the invoice and quote state before refunding.")
        recorded = sum(item.amount_cents for item in previous)
        if amount > paid_cents - recorded:
            raise ValueError("Refund exceeds this invoice's remaining paid amount.")
        # Stripe InvoicePayment maps this invoice to its actual PaymentIntent.
        try:
            remote = await asyncio.to_thread(stripe.Invoice.retrieve, remote_id)
            payments = await asyncio.to_thread(stripe.InvoicePayment.list, invoice=remote_id, status="paid", limit=2)
            if (
                remote.id != remote_id
                or remote.status != "paid"
                or remote.currency != "usd"
                or remote.total != paid_cents
            ):
                raise ValueError("Invoice payment differs from the local record. Review Stripe.")
            if payments.has_more or len(payments.data) != 1:
                raise ValueError("This invoice has multiple or unsupported payments. Review Stripe individually.")
            payment = payments.data[0]
            detail = payment.payment
            intent_id = detail.payment_intent if detail.type == "payment_intent" else None
            if (
                payment.invoice != remote_id
                or payment.status != "paid"
                or payment.currency != "usd"
                or payment.amount_paid != paid_cents
                or not intent_id
            ):
                raise ValueError("The invoice payment cannot be safely refunded automatically.")
            intent = await asyncio.to_thread(stripe.PaymentIntent.retrieve, intent_id)
            if (
                intent.id != intent_id
                or intent.status != "succeeded"
                or intent.currency != "usd"
                or intent.amount_received != paid_cents
                or not intent.latest_charge
            ):
                raise ValueError("The invoice charge needs manual Stripe review.")
            charge = await asyncio.to_thread(stripe.Charge.retrieve, intent.latest_charge)
            if (
                charge.id != intent.latest_charge
                or charge.payment_intent != intent_id
                or charge.amount_refunded != recorded
            ):
                raise ValueError("Stripe shows refunds not recorded here. Reconcile before another refund.")
        except ValueError:
            raise
        except Exception:
            raise ValueError("Could not verify the invoice payment in Stripe. No refund was requested.") from None
        row = InvoiceRefund(
            **{source: pk},
            amount_cents=amount,
            payment_intent_id=intent_id,
            status="issuing",
            reason=reason,
            idempotency_key=key,
            actor_id=actor_id,
        )
        db.add(row)
        owner.status = "review"  # Pause all future sends and changes, including scheduled installments.
        await db.commit()
        refund_id = row.id
    try:
        remote_refund = await asyncio.to_thread(
            stripe.Refund.create,
            payment_intent=intent_id,
            amount=amount,
            reason="requested_by_customer",
            metadata={"invoice_refund_id": str(refund_id), "invoice_id": remote_id},
            idempotency_key=f"invoice-refund-{key}",
        )
    except Exception:
        async with session_scope() as db:
            row = await db.get(InvoiceRefund, refund_id)
            row.status = "review"
            await db.commit()
        raise ValueError("Refund outcome is uncertain. Check Stripe; do not submit another refund.") from None
    async with session_scope() as db:
        row = await db.scalar(select(InvoiceRefund).where(InvoiceRefund.id == refund_id).with_for_update())
        row.stripe_refund_id = remote_refund.id
        row.status = "review"
        await db.commit()
    if (
        remote_refund.status != "succeeded"
        or remote_refund.amount != amount
        or remote_refund.currency != "usd"
        or remote_refund.payment_intent != intent_id
    ):
        async with session_scope() as db:
            return await db.get(InvoiceRefund, refund_id)
    async with session_scope() as db:
        row = await db.scalar(select(InvoiceRefund).where(InvoiceRefund.id == refund_id).with_for_update())
        await _complete_refund(db, row, remote_refund.id)
        await db.commit()
        return row
