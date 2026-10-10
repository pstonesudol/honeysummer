"""Read-only Stripe-invoice exposure, separate from paid-order revenue."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .models import BouquetProposal, Inquiry, InvoiceRefund, WeddingInvoice, WeddingQuote


def _day(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        value = datetime.fromisoformat(value) if "T" in value else date.fromisoformat(value)
    # SQLite drops timezone info in local tests; persisted timestamps are UTC.
    if not value.tzinfo:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(ZoneInfo("America/New_York")).date()


def _invoice_due(quote: WeddingQuote, invoice: WeddingInvoice) -> date | None:
    if invoice.step == "amended":
        return quote.amendment_due_date or _day(invoice.created_at + timedelta(days=7))
    if invoice.step == "balance":
        return quote.balance_due_date or _day(invoice.created_at + timedelta(days=7))
    if invoice.step.startswith("part_"):
        index = int(invoice.step[5:]) - 1
        if 0 <= index < len(quote.installments or []):
            return date.fromisoformat(quote.installments[index]["due_date"])
        return None
    return quote.initial_due_date or _day(invoice.created_at + timedelta(days=7))


async def invoice_balance_rows(db, *, today: date | None = None) -> list[dict]:
    """Only count locally recorded open invoices; uncertain sends are review, not debt."""
    today = today or datetime.now(ZoneInfo("America/New_York")).date()
    rows = []
    proposals = (
        await db.execute(
            select(BouquetProposal, Inquiry)
            .join(Inquiry, Inquiry.id == BouquetProposal.inquiry_id)
            .where(BouquetProposal.status.in_(("sent", "review")), BouquetProposal.stripe_invoice_id.is_not(None))
        )
    ).all()
    refunds = (await db.scalars(select(InvoiceRefund).where(InvoiceRefund.status == "succeeded"))).all()
    proposal_refunds = defaultdict(int)
    invoice_refunds = defaultdict(int)
    for refund in refunds:
        if refund.proposal_id is not None:
            proposal_refunds[refund.proposal_id] += refund.amount_cents
        else:
            invoice_refunds[refund.wedding_invoice_id] += refund.amount_cents
    for proposal, inquiry in proposals:
        if not proposal.history:
            continue
        total = proposal.history[-1]["draft"].get("total_cents", 0)
        if total <= 0:
            continue
        due = _day(proposal.history[-1]["sent_at"]) + timedelta(days=7)
        rows.append(
            dict(
                kind="Bouquet",
                id=proposal.id,
                url=f"/admin/proposals/{proposal.id}",
                customer=inquiry.name,
                title=proposal.history[-1]["draft"].get("title", "Bouquet"),
                total_cents=total,
                verified_paid_cents=0,
                refunded_cents=proposal_refunds[proposal.id],
                balance_cents=total,
                open_cents=total if proposal.status == "sent" else 0,
                due=due,
                status=proposal.status,
                needs_review=proposal.status != "sent",
            )
        )
    quotes = (
        await db.execute(
            select(WeddingQuote, Inquiry)
            .join(Inquiry, Inquiry.id == WeddingQuote.inquiry_id)
            .where(
                WeddingQuote.status.in_(
                    (
                        "scheduled",
                        "sent",
                        "deposit_paid",
                        "balance_sent",
                        "installment_paid",
                        "installment_sent",
                        "amendment_ready",
                        "amendment_sent",
                        "review",
                        "issuing",
                    )
                ),
                WeddingQuote.order_id.is_(None),
            )
        )
    ).all()
    invoices_by_quote = defaultdict(list)
    if quotes:
        invoices = (
            await db.scalars(
                select(WeddingInvoice).where(WeddingInvoice.quote_id.in_([quote.id for quote, _ in quotes]))
            )
        ).all()
        for invoice in invoices:
            invoices_by_quote[invoice.quote_id].append(invoice)
    for quote, inquiry in quotes:
        amended = (
            quote.amendments[-1] if quote.status in ("amendment_ready", "amendment_sent") and quote.amendments else None
        )
        total = (amended["draft"] if amended else quote.snapshot or {}).get("total_cents", 0)
        if total <= 0:
            continue
        invoices = invoices_by_quote[quote.id]
        verified_paid = sum(invoice.amount_cents for invoice in invoices if invoice.status == "paid")
        refunded = sum(invoice_refunds[invoice.id] for invoice in invoices)
        if verified_paid >= total and not amended:
            continue
        open_invoices = [invoice for invoice in invoices if invoice.status == "sent"]
        open_amount = sum(invoice.amount_cents for invoice in open_invoices)
        due = min((day for invoice in open_invoices if (day := _invoice_due(quote, invoice))), default=None)
        rows.append(
            dict(
                kind="Wedding",
                id=quote.id,
                url=f"/admin/weddings/{quote.id}",
                customer=inquiry.name,
                title=(amended["draft"] if amended else quote.snapshot).get("title", "Wedding quote"),
                total_cents=total,
                verified_paid_cents=verified_paid,
                refunded_cents=refunded,
                balance_cents=amended["amount_cents"] if amended else total - verified_paid,
                open_cents=open_amount,
                due=due,
                status=quote.status,
                needs_review=quote.status in ("review", "issuing"),
            )
        )
    for row in rows:
        row["overdue"] = bool(row["open_cents"] and row["due"] and row["due"] < today)
    return sorted(
        rows,
        key=lambda row: (not row["needs_review"], not row["overdue"], row["due"] or date.max, row["kind"], row["id"]),
    )
