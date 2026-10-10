"""Report-only Stripe invoice refund reconciliation; never changes money or stock.

Run python -m app.invoice_refund_audit. Findings are recorded in Needs attention.
"""

import asyncio
import sys

import stripe
from sqlalchemy import select

from .db import session_scope
from .models import BouquetProposal, InvoiceRefund, WeddingInvoice
from .reconcile import record_run
from .settings import get_settings


async def audit() -> list[str]:
    """Compare successful local refunds with original Stripe invoice charges."""
    if not get_settings().stripe_secret_key:
        raise ValueError("Stripe must be configured to audit invoice refunds.")
    stripe.api_key = get_settings().stripe_secret_key
    async with session_scope() as db:
        invoices = (await db.scalars(select(WeddingInvoice).where(WeddingInvoice.status == "paid"))).all()
        proposals = (await db.scalars(select(BouquetProposal).where(BouquetProposal.order_id.is_not(None)))).all()
        refunds = (await db.scalars(select(InvoiceRefund))).all()
    sources = [("wedding", row.id, row.stripe_invoice_id, row.amount_cents) for row in invoices]
    sources += [
        ("bouquet", row.id, row.stripe_invoice_id, row.history[-1]["draft"]["total_cents"])
        for row in proposals
        if row.history
    ]
    findings = []
    for kind, pk, invoice_id, total in sources:
        local = [row for row in refunds if (row.wedding_invoice_id if kind == "wedding" else row.proposal_id) == pk]
        recorded = sum(row.amount_cents for row in local if row.status == "succeeded")
        label = f"{kind.capitalize()} invoice record #{pk} ({invoice_id})"
        try:
            payments = await asyncio.to_thread(stripe.InvoicePayment.list, invoice=invoice_id, status="paid", limit=2)
            if payments.has_more or len(payments.data) != 1:
                findings.append(f"{label}: multiple/unsupported payments; manual review")
                continue
            payment = payments.data[0]
            if (
                payment.invoice != invoice_id
                or payment.currency != "usd"
                or payment.amount_paid != total
                or payment.status != "paid"
                or payment.payment.type != "payment_intent"
            ):
                findings.append(f"{label}: invoice payment differs; manual review")
                continue
            intent = await asyncio.to_thread(stripe.PaymentIntent.retrieve, payment.payment.payment_intent)
            charge = await asyncio.to_thread(stripe.Charge.retrieve, intent.latest_charge)
            if (
                intent.id != payment.payment.payment_intent
                or intent.currency != "usd"
                or intent.status != "succeeded"
                or intent.amount_received != total
                or charge.id != intent.latest_charge
                or charge.payment_intent != intent.id
            ):
                findings.append(f"{label}: original charge differs; manual review")
                continue
            if charge.amount_refunded != recorded:
                findings.append(
                    f"{label}: Stripe refunded {charge.amount_refunded} cents; local journal {recorded} cents. "
                    "Verify and import external refund IDs on the invoice page; do not retry collection/refunds."
                )
            if any(row.status != "succeeded" for row in local):
                findings.append(f"{label}: uncertain refund request; verify the exact Stripe outcome")
        except Exception as exc:
            findings.append(
                f"{label}: Stripe verification unavailable ({type(exc).__name__}); no payment state changed"
            )
    return findings


async def audit_and_record() -> list[str]:
    """Keep auditing and database persistence on the same async connection loop."""
    findings = await audit()
    await record_run(findings, applied=False, full=True)
    return findings


def main():
    """Audit all invoice receipts and persist report-only findings."""
    findings = asyncio.run(audit_and_record())
    for finding in findings:
        print(finding)
    if findings:
        sys.exit(1)
    print("Invoice refund journals agree with supported Stripe payments.")


if __name__ == "__main__":
    main()
