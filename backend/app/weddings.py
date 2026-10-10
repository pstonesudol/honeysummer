"""Wedding quote invoices: full upfront or separate deposit and balance."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import stripe
from sqlalchemy import select

from .db import session_scope
from .form_errors import FieldValidationError
from .models import (
    BouquetProposal,
    Inquiry,
    InvoiceRefund,
    Order,
    OrderItem,
    OrderNotification,
    StripeEvent,
    WeddingInvoice,
    WeddingQuote,
)
from .payments import deliver_notifications
from .proposals import cents
from .settings import get_settings

EASTERN = ZoneInfo("America/New_York")


def eastern_today() -> date:
    """Return today's date in Eastern time."""
    return datetime.now(EASTERN).date()


def validate_schedule(form, payment_mode: str, *, today: date | None = None) -> dict:
    """Keep agreed invoice dates separate from quote amounts and free-form copy."""
    today = today or eastern_today()
    initial_mode = str(form.get("initial_send_mode", "manual"))
    balance_mode = str(form.get("balance_send_mode", "manual")) if payment_mode == "deposit" else "manual"
    if initial_mode not in ("manual", "automatic"):
        raise FieldValidationError("Choose manual or automatic invoice sending.", "initial_send_mode")
    if balance_mode not in ("manual", "automatic"):
        raise FieldValidationError("Choose manual or automatic invoice sending.", "balance_send_mode")

    def chosen_date(name):
        raw = str(form.get(name, "")).strip()
        try:
            return date.fromisoformat(raw) if raw else None
        except ValueError:
            raise FieldValidationError(f"Enter a valid {name.replace('_', ' ')}.", name) from None

    first_send = chosen_date("initial_send_date") if initial_mode == "automatic" else None
    first_due = chosen_date("initial_due_date")
    balance_send = chosen_date("balance_send_date") if balance_mode == "automatic" else None
    balance_due = chosen_date("balance_due_date") if payment_mode == "deposit" else None
    if initial_mode == "automatic" and not first_send:
        raise FieldValidationError("Choose when to send the first invoice automatically.", "initial_send_date")
    if payment_mode == "deposit" and balance_mode == "automatic" and not balance_send:
        raise FieldValidationError("Choose when to send the balance invoice automatically.", "balance_send_date")
    if initial_mode == "automatic" and not first_due:
        raise FieldValidationError("Choose a due date for the scheduled first invoice.", "initial_due_date")
    if payment_mode == "deposit" and balance_mode == "automatic" and not balance_due:
        raise FieldValidationError("Choose a due date for the scheduled balance invoice.", "balance_due_date")
    if payment_mode == "deposit" and balance_due and not first_due:
        raise FieldValidationError("Set the deposit due date before choosing a balance due date.", "initial_due_date")
    if first_send and first_send < today:
        raise FieldValidationError("Scheduled sending cannot start in the past.", "initial_send_date")
    if balance_send and balance_send < today:
        raise FieldValidationError("Scheduled sending cannot start in the past.", "balance_send_date")
    if first_due and first_due < (first_send or today):
        raise FieldValidationError(
            "Each due date must be on or after its sending date and not in the past.", "initial_due_date"
        )
    if balance_due and balance_due < (balance_send or today):
        raise FieldValidationError(
            "Each due date must be on or after its sending date and not in the past.", "balance_due_date"
        )
    if payment_mode == "deposit" and first_due and balance_due and balance_due < first_due:
        raise FieldValidationError("Balance must be due on or after the deposit due date.", "balance_due_date")
    return dict(
        initial_send_mode=initial_mode,
        initial_send_date=first_send,
        initial_due_date=first_due,
        balance_send_mode=balance_mode,
        balance_send_date=balance_send,
        balance_due_date=balance_due,
    )


def installment_step(index: int) -> str:
    """Return the invoice step name for a zero-based installment index."""
    return f"part_{index + 1:02d}"


def validate_installments(form, total_cents: int, *, today: date | None = None) -> list[dict]:
    """Validate exact integer-cent sum and chronological per-payment terms."""
    today = today or eastern_today()
    raw_ids = str(form.get("installment_ids", "")).strip()
    if raw_ids:
        tokens = raw_ids.split(",")
        if not all(token.isdigit() and 1 <= int(token) <= 100000 for token in tokens):
            raise FieldValidationError("Installment identifiers are invalid.", "installment_ids")
        indexes = [int(token) for token in tokens]
    else:
        # Accept older forms that posted fixed numbered amount fields.
        indexes = sorted(
            int(match.group(1)) for key in form.keys() if (match := re.fullmatch(r"installment_amount_(\d+)", str(key)))
        )
    if len(indexes) != len(set(indexes)) or len(indexes) > 200:
        raise FieldValidationError("Add no more than 200 distinct installments.", "installment_ids")
    parts = []
    previous_due = None
    previous_send = None
    for index in indexes:
        kind = str(form.get(f"installment_type_{index}", "amount"))
        if kind not in ("amount", "percent"):
            raise FieldValidationError(
                "Choose a dollar amount or percentage for each installment.", f"installment_type_{index}"
            )
        raw_amount = str(form.get(f"installment_amount_{index}", "")).strip()
        raw_percent = str(form.get(f"installment_percent_{index}", "")).strip()
        if kind == "percent":
            try:
                percent = Decimal(raw_percent)
            except InvalidOperation:
                raise FieldValidationError(
                    "Enter a valid installment percentage.", f"installment_percent_{index}"
                ) from None
            if not percent.is_finite() or not 0 < percent <= 100 or percent.as_tuple().exponent < -2:
                raise FieldValidationError(
                    "Enter a percentage between 0 and 100 with at most two decimals.", f"installment_percent_{index}"
                )
            amount = int((Decimal(total_cents) * percent / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        else:
            percent = None
            try:
                amount = cents(raw_amount)
            except ValueError as exc:
                raise FieldValidationError(str(exc), f"installment_amount_{index}") from None
        mode = str(form.get(f"installment_send_mode_{index}", "manual"))
        if mode not in ("manual", "automatic"):
            raise FieldValidationError("Choose manual or automatic invoice sending.", f"installment_send_mode_{index}")
        if amount < 50:
            raise FieldValidationError(
                "Every installment must be at least $0.50.",
                f"installment_percent_{index}" if kind == "percent" else f"installment_amount_{index}",
            )

        def parse_date(field, index=index):
            raw = str(form.get(f"installment_{field}_{index}", "")).strip()
            try:
                return date.fromisoformat(raw) if raw else None
            except ValueError:
                raise FieldValidationError(
                    f"Enter a valid installment {field.replace('_', ' ')}.", f"installment_{field}_{index}"
                ) from None

        send = parse_date("send_date") if mode == "automatic" else None
        due = parse_date("due_date")
        if not due:
            raise FieldValidationError("Each installment needs a due date.", f"installment_due_date_{index}")
        if mode == "automatic" and not send:
            raise FieldValidationError("Automatic sending needs a send date.", f"installment_send_date_{index}")
        if send and send < today:
            raise FieldValidationError(
                "Installment send dates cannot be in the past.", f"installment_send_date_{index}"
            )
        if due < (send or today):
            raise FieldValidationError(
                "Installment due dates cannot be in the past or before sending.", f"installment_due_date_{index}"
            )
        if previous_due and due <= previous_due:
            raise FieldValidationError("Installment due dates must increase in order.", f"installment_due_date_{index}")
        if previous_send and send and send < previous_send:
            raise FieldValidationError(
                "Installment send dates must not move backward.", f"installment_send_date_{index}"
            )
        parts.append(
            dict(
                amount_cents=amount,
                amount_type=kind,
                percent=str(percent) if percent is not None else None,
                send_mode=mode,
                send_date=send.isoformat() if send else None,
                due_date=due.isoformat(),
            )
        )
        previous_due, previous_send = due, send or previous_send
    if not 2 <= len(parts) <= 200:
        raise FieldValidationError("Enter between two and 200 installments.", "installment_ids")
    if (
        all(part["amount_type"] == "percent" for part in parts)
        and sum(Decimal(part["percent"]) for part in parts) == 100
    ):
        # Assign rounding pennies to the final payment, without changing the agreed total.
        parts[-1]["amount_cents"] = total_cents - sum(part["amount_cents"] for part in parts[:-1])
        if parts[-1]["amount_cents"] < 50:
            raise FieldValidationError(
                "Every installment must be at least $0.50 after rounding.", f"installment_percent_{indexes[-1]}"
            )
    actual_cents = sum(part["amount_cents"] for part in parts)
    if actual_cents != total_cents:
        difference = total_cents - actual_cents
        action = "Add" if difference > 0 else "Reduce payments by"
        raise FieldValidationError(
            f"Installments must total exactly ${total_cents / 100:.2f}. "
            f"Current payments total ${actual_cents / 100:.2f}. "
            f"{action} ${abs(difference) / 100:.2f}{' to the payments' if difference > 0 else ''}.",
            "installment_total",
        )
    return parts


def due_timestamp(day: date) -> int:
    """Stripe due_date is an epoch second; show end-of-day in Eastern time."""
    return int(datetime.combine(day, time(23, 59, 59), EASTERN).timestamp())


def validate_quote(form) -> tuple[dict, str, int]:
    """Validate a wedding quote form into itemized totals and payment mode."""
    title = str(form.get("title", "")).strip()
    description = str(form.get("description", "")).strip()
    terms = str(form.get("terms", "")).strip()
    location = str(form.get("location", "")).strip()
    mode = str(form.get("payment_mode", ""))
    for field, value, limit in (
        ("title", title, 160),
        ("description", description, 2000),
        ("terms", terms, 2000),
        ("location", location, 500),
    ):
        if not value:
            raise FieldValidationError(f"{field.capitalize()} is required.", field)
        if len(value) > limit:
            raise FieldValidationError(f"{field.capitalize()} must be {limit} characters or fewer.", field)
    if mode not in ("full", "deposit", "installments"):
        raise FieldValidationError("Choose a payment plan.", "payment_mode")
    raw_ids = str(form.get("line_ids", "")).strip()
    if raw_ids:
        tokens = raw_ids.split(",")
        if not all(token.isdigit() and 1 <= int(token) <= 100000 for token in tokens):
            raise FieldValidationError("Quote line identifiers are invalid.", "line_ids")
        indexes = [int(token) for token in tokens]
    else:
        indexes = sorted(int(match.group(1)) for key in form.keys() if (match := re.fullmatch(r"name_(\d+)", str(key))))
    if len(indexes) != len(set(indexes)) or len(indexes) > 200:
        raise FieldValidationError("Add no more than 200 distinct quote lines.", "line_ids")
    lines = []
    for index in indexes:
        name = str(form.get(f"name_{index}", "")).strip()
        if not name:
            if str(form.get(f"quantity_{index}", "")).strip() or str(form.get(f"price_{index}", "")).strip():
                raise FieldValidationError("Name each quote line that has a quantity or price.", f"name_{index}")
            continue
        try:
            quantity = int(str(form.get(f"quantity_{index}", "")))
        except ValueError:
            raise FieldValidationError("Enter a valid line quantity.", f"quantity_{index}") from None
        if len(name) > 160:
            raise FieldValidationError("Use a name of 160 characters or fewer.", f"name_{index}")
        if not 1 <= quantity <= 9999:
            raise FieldValidationError("Enter a quantity from 1–9999.", f"quantity_{index}")
        try:
            price = cents(str(form.get(f"price_{index}", "")))
        except ValueError as exc:
            raise FieldValidationError(str(exc), f"price_{index}") from None
        lines.append(dict(name=name, quantity=quantity, unit_cents=price))
    if not lines:
        raise FieldValidationError("Add at least one itemized service or arrangement.", "line_ids")
    total = sum(line["unit_cents"] * line["quantity"] for line in lines)
    if not 50 <= total <= 99999999:
        raise FieldValidationError("Total must be between $0.50 and $999,999.99.", "line_ids")
    try:
        deposit = cents(str(form.get("deposit", ""))) if mode == "deposit" else 0
    except ValueError as exc:
        raise FieldValidationError(str(exc), "deposit") from None
    if mode == "deposit" and not 50 <= deposit <= total - 50:
        raise FieldValidationError("Deposit and remaining balance must each be at least $0.50.", "deposit")
    return (
        dict(title=title, description=description, terms=terms, location=location, lines=lines, total_cents=total),
        mode,
        deposit,
    )


async def approve_wedding_schedule(quote_id: int) -> None:
    """Owner approval freezes the quote before an independent job can send it."""
    async with session_scope() as db:
        quote = await db.scalar(select(WeddingQuote).where(WeddingQuote.id == quote_id).with_for_update())
        if (
            not quote
            or quote.status != "draft"
            or quote.initial_send_mode != "automatic"
            or not quote.initial_send_date
        ):
            raise ValueError("Save an automatic sending date on a draft quote first.")
        if (
            quote.initial_send_date < eastern_today()
            or not quote.initial_due_date
            or quote.initial_due_date < quote.initial_send_date
        ):
            raise ValueError("The sending or due date is no longer valid. Edit the quote first.")
        if quote.payment_mode == "installments":
            if not quote.installments or date.fromisoformat(quote.installments[0]["due_date"]) < eastern_today():
                raise ValueError("The first installment due date has passed. Edit the quote first.")
        else:
            validate_schedule(
                dict(
                    initial_send_mode=quote.initial_send_mode,
                    initial_send_date=quote.initial_send_date.isoformat(),
                    initial_due_date=quote.initial_due_date.isoformat(),
                    balance_send_mode=quote.balance_send_mode,
                    balance_send_date=quote.balance_send_date.isoformat() if quote.balance_send_date else "",
                    balance_due_date=quote.balance_due_date.isoformat() if quote.balance_due_date else "",
                ),
                quote.payment_mode,
            )
        if "total_cents" not in (quote.draft or {}):
            raise ValueError("Complete the itemized quote before scheduling.")
        quote.snapshot = quote.draft
        quote.status = "scheduled"
        quote.activity = [
            *(quote.activity or []),
            dict(
                action="first invoice scheduled",
                at=datetime.now(UTC).isoformat(),
                send_date=quote.initial_send_date.isoformat(),
            ),
        ]
        await db.commit()


async def next_installment_index(db, quote: WeddingQuote) -> int | None:
    """Return the next unpaid installment index, or None when none is due."""
    rows = (
        await db.scalars(
            select(WeddingInvoice)
            .where(
                WeddingInvoice.quote_id == quote.id, WeddingInvoice.step.like("part_%"), WeddingInvoice.status != "void"
            )
            .order_by(WeddingInvoice.id)
        )
    ).all()
    if any(row.status != "paid" or row.step != installment_step(index) for index, row in enumerate(rows)):
        return None
    return len(rows) if len(rows) < len(quote.installments or []) else None


async def agree_revised_wedding(quote_id: int, form, *, actor_id: int) -> None:
    """Freeze a new itemized agreement, crediting only verified payments net of refunds."""

    class RevisedForm:
        def get(self, key, default=None):
            return "full" if key == "payment_mode" else form.get(key, default)

        def keys(self):
            return form.keys()

    draft, _, _ = validate_quote(RevisedForm())
    reference = str(form.get("acceptance_reference", "")).strip()
    if not 1 <= len(reference) <= 255 or str(form.get("customer_accepted", "")) != "on":
        raise FieldValidationError("Record the customer's written acceptance and confirm it.", "acceptance_reference")
    try:
        due = date.fromisoformat(str(form.get("amendment_due_date", "")))
    except ValueError:
        raise FieldValidationError("Choose a valid due date for the revised invoice.", "amendment_due_date") from None
    if due < eastern_today():
        raise FieldValidationError("The revised invoice due date cannot be in the past.", "amendment_due_date")
    async with session_scope() as db:
        quote = await db.scalar(select(WeddingQuote).where(WeddingQuote.id == quote_id).with_for_update())
        if (
            not quote
            or quote.status != "review"
            or quote.order_id
            or quote.payment_mode not in ("deposit", "installments")
        ):
            raise ValueError("Only a partially refunded, unpaid wedding in review can be amended.")
        invoices = (await db.scalars(select(WeddingInvoice).where(WeddingInvoice.quote_id == quote_id))).all()
        if not invoices or any(invoice.status not in ("paid", "void") for invoice in invoices):
            raise ValueError("Resolve outstanding or uncertain Stripe invoices before changing the agreement.")
        paid = [invoice for invoice in invoices if invoice.status == "paid"]
        if not paid:
            raise ValueError("No verified paid invoice exists to credit.")
        refunds = (
            await db.scalars(
                select(InvoiceRefund).where(InvoiceRefund.wedding_invoice_id.in_([invoice.id for invoice in paid]))
            )
        ).all()
        if not refunds or any(item.status != "succeeded" for item in refunds):
            raise ValueError("A confirmed partial refund is required; uncertain refunds need Stripe review.")
        gross = sum(invoice.amount_cents for invoice in paid)
        refunded = sum(item.amount_cents for item in refunds)
        retained = gross - refunded
        if not 0 < retained < gross:
            raise ValueError("There is no retained partial payment. Close a fully refunded wedding instead.")
        remainder = draft["total_cents"] - retained
        if remainder < 50:
            raise FieldValidationError(
                "Revised itemized total must leave at least $0.50 due after retained payments.", "line_ids"
            )
        quote.amendments = [
            *(quote.amendments or []),
            dict(
                version=len(quote.amendments or []) + 1,
                draft=draft,
                retained_paid_cents=retained,
                refunded_cents=refunded,
                amount_cents=remainder,
                acceptance_reference=reference,
                actor_id=actor_id,
                agreed_at=datetime.now(UTC).isoformat(),
                due_date=due.isoformat(),
            ),
        ]
        quote.amendment_due_date = due
        quote.status = "amendment_ready"
        quote.activity = [
            *(quote.activity or []),
            dict(
                action="revised agreement accepted",
                actor=actor_id,
                at=datetime.now(UTC).isoformat(),
                remaining_cents=remainder,
                version=len(quote.amendments),
            ),
        ]
        await db.commit()


async def run_wedding_schedule(*, apply: bool = False, today: date | None = None) -> list[str]:
    """One bounded run; a platform scheduler must invoke it repeatedly."""
    today = today or eastern_today()
    async with session_scope() as db:
        initial_ids = (
            await db.scalars(
                select(WeddingQuote.id)
                .where(
                    WeddingQuote.status == "scheduled",
                    WeddingQuote.initial_send_mode == "automatic",
                    WeddingQuote.initial_send_date <= today,
                )
                .order_by(WeddingQuote.id)
                .limit(100)
            )
        ).all()
        balance_ids = (
            await db.scalars(
                select(WeddingQuote.id)
                .where(
                    WeddingQuote.status == "deposit_paid",
                    WeddingQuote.balance_send_mode == "automatic",
                    WeddingQuote.balance_send_date <= today,
                )
                .order_by(WeddingQuote.id)
                .limit(100)
            )
        ).all()
        part_ids = []
        offset = 0
        while len(part_ids) < 100:
            awaiting_parts = (
                await db.scalars(
                    select(WeddingQuote)
                    .where(WeddingQuote.status == "installment_paid", WeddingQuote.payment_mode == "installments")
                    .order_by(WeddingQuote.id)
                    .offset(offset)
                    .limit(100)
                )
            ).all()
            for quote in awaiting_parts:
                index = await next_installment_index(db, quote)
                if index is not None:
                    part = quote.installments[index]
                    if part["send_mode"] == "automatic" and date.fromisoformat(part["send_date"]) <= today:
                        part_ids.append((quote.id, installment_step(index)))
                        if len(part_ids) == 100:
                            break
            if len(awaiting_parts) < 100:
                break
            offset += 100
    findings = []
    for quote_id, step in [
        *((id, "initial") for id in initial_ids),
        *((id, "balance") for id in balance_ids),
        *part_ids,
    ]:
        if not apply:
            findings.append(f"Wedding quote #{quote_id}: {step} invoice is due to send")
            continue
        try:
            if step == "initial":
                async with session_scope() as db:
                    quote = await db.get(WeddingQuote, quote_id)
                    invoice_step = installment_step(0) if quote.payment_mode == "installments" else quote.payment_mode
            else:
                invoice_step = step
            invoice_id = await send_wedding_invoice(quote_id, invoice_step, scheduled=True)
            findings.append(f"Wedding quote #{quote_id}: sent {invoice_step} invoice {invoice_id}")
        except Exception as exc:
            # A failed/ambiguous send is left for operator review, never blindly retried.
            findings.append(f"Wedding quote #{quote_id}: {step} send needs review ({type(exc).__name__}: {exc})")
    return findings


async def send_wedding_invoice(quote_id: int, step: str, *, scheduled: bool = False) -> str:
    """Persist an issuing marker before Stripe calls; never repeat an uncertain send."""

    settings = get_settings()
    if not settings.stripe_secret_key or not settings.stripe_webhook_secret:
        raise ValueError("Stripe invoices and a signed webhook must be configured first.")
    part_index = int(step[5:]) - 1 if step.startswith("part_") and step[5:].isdigit() else None
    if step not in ("full", "deposit", "balance", "amended") and (
        part_index is None or part_index < 0 or step != installment_step(part_index)
    ):
        raise ValueError("Unknown invoice step.")
    stripe.api_key = settings.stripe_secret_key
    async with session_scope() as db:
        quote = await db.scalar(select(WeddingQuote).where(WeddingQuote.id == quote_id).with_for_update())
        if not quote:
            raise ValueError("This invoice cannot be sent in the current state.")
        if step == "amended":
            if quote.status != "amendment_ready" or not quote.amendments or quote.order_id or scheduled:
                raise ValueError("A customer-accepted revised agreement is required before sending.")
            earlier = (await db.scalars(select(WeddingInvoice).where(WeddingInvoice.quote_id == quote_id))).all()
            if any(row.status not in ("paid", "void") for row in earlier):
                raise ValueError("An earlier invoice is still payable or uncertain. Review it in Stripe first.")
            paid_rows = [row for row in earlier if row.status == "paid"]
            refund_rows = (
                await db.scalars(
                    select(InvoiceRefund).where(InvoiceRefund.wedding_invoice_id.in_([row.id for row in paid_rows]))
                )
            ).all()
            if any(refund.status != "succeeded" for refund in refund_rows) or (
                sum(row.amount_cents for row in paid_rows) - sum(refund.amount_cents for refund in refund_rows)
                != quote.amendments[-1]["retained_paid_cents"]
            ):
                raise ValueError("Verified retained payments changed. Review the customer agreement before sending.")
            send_mode, send_date, due_date = "manual", None, quote.amendment_due_date
        elif part_index is not None:
            if quote.payment_mode != "installments" or part_index >= len(quote.installments or []):
                raise ValueError("This installment does not exist.")
            if part_index == 0:
                if quote.status != ("scheduled" if scheduled else "draft"):
                    raise ValueError("The first installment is not ready to send.")
            elif quote.status != "installment_paid" or await next_installment_index(db, quote) != part_index:
                raise ValueError("Pay the previous installment before sending the next one.")
            part = quote.installments[part_index]
            send_mode = part["send_mode"]
            send_date = date.fromisoformat(part["send_date"]) if part["send_date"] else None
            due_date = date.fromisoformat(part["due_date"])
        else:
            if (step == "balance" and (quote.payment_mode != "deposit" or quote.status != "deposit_paid")) or (
                step != "balance"
                and (quote.status != ("scheduled" if scheduled else "draft") or quote.payment_mode != step)
            ):
                raise ValueError("This invoice cannot be sent in the current state.")
            send_mode = quote.balance_send_mode if step == "balance" else quote.initial_send_mode
            send_date = quote.balance_send_date if step == "balance" else quote.initial_send_date
            due_date = quote.balance_due_date if step == "balance" else quote.initial_due_date
        if scheduled != (send_mode == "automatic"):
            raise ValueError("This invoice is assigned to a different sending mode.")
        if scheduled and (not send_date or send_date > eastern_today()):
            raise ValueError("The scheduled send date has not arrived.")
        if due_date and due_date < eastern_today():
            raise ValueError("The invoice due date has passed. Review the quote before sending.")
        inquiry = await db.get(Inquiry, quote.inquiry_id)
        if not quote.draft or "total_cents" not in quote.draft or not inquiry or inquiry.kind != "wedding":
            raise ValueError("Complete the wedding quote before sending.")
        previous = (
            await db.scalars(
                select(WeddingInvoice)
                .where(WeddingInvoice.quote_id == quote_id, WeddingInvoice.step == step)
                .order_by(WeddingInvoice.revision.desc())
            )
        ).all()
        if previous and previous[0].status != "void":
            raise ValueError("An earlier invoice for this payment is still outstanding or needs review.")
        revision = previous[0].revision + 1 if previous else 1
        snapshot = (
            quote.amendments[-1]["draft"]
            if step == "amended"
            else quote.snapshot
            if step == "balance" or (part_index is not None and part_index > 0)
            else quote.draft
        )
        amount = (
            quote.amendments[-1]["amount_cents"]
            if step == "amended"
            else quote.installments[part_index]["amount_cents"]
            if part_index is not None
            else snapshot["total_cents"] - quote.deposit_cents
            if step == "balance"
            else quote.deposit_cents
            if step == "deposit"
            else snapshot["total_cents"]
        )
        row = WeddingInvoice(quote_id=quote_id, step=step, revision=revision, status="issuing", amount_cents=amount)
        db.add(row)
        if step not in ("balance", "amended") and part_index in (None, 0):
            quote.snapshot = quote.draft
        quote.status = "issuing"
        await db.commit()
        email, name, customer_id = inquiry.email, inquiry.name, quote.stripe_customer_id
    key = f"wedding-{quote_id}-{step}-v{revision}"
    try:
        customer = (
            await asyncio.to_thread(stripe.Customer.retrieve, customer_id)
            if customer_id
            else await asyncio.to_thread(
                stripe.Customer.create, email=email, name=name, idempotency_key=f"{key}-customer"
            )
        )
        payment_label = (
            f"Installment {part_index + 1} of {len(quote.installments)}"
            if part_index is not None
            else "Revised balance"
            if step == "amended"
            else step.capitalize()
        )
        memo = (
            f"{snapshot['title']}\nQuote total: ${snapshot['total_cents'] / 100:.2f}; "
            f"{payment_label}: ${amount / 100:.2f}\nEvent: {snapshot['location']}"
        )
        if len(memo) > 500:
            memo = memo[:497] + "..."
        invoice = await asyncio.to_thread(
            stripe.Invoice.create,
            customer=customer.id,
            collection_method="send_invoice",
            **({"due_date": due_timestamp(due_date)} if due_date else {"days_until_due": 7}),
            auto_advance=False,
            pending_invoice_items_behavior="exclude",
            metadata={"wedding_quote_id": str(quote_id), "step": step, "revision": str(revision)},
            description=memo,
            idempotency_key=f"{key}-invoice",
        )
        for index, line in enumerate(snapshot["lines"]):
            if step == "full":
                item = dict(
                    unit_amount_decimal=str(line["unit_cents"]), quantity=line["quantity"], description=line["name"]
                )
            else:
                item = dict(
                    amount=0,
                    description=(
                        f"Quote scope (included in ${snapshot['total_cents'] / 100:.2f} total): "
                        f"{line['quantity']} × {line['name']} — ${line['quantity'] * line['unit_cents'] / 100:.2f}"
                    ),
                )
            await asyncio.to_thread(
                stripe.InvoiceItem.create,
                customer=customer.id,
                invoice=invoice.id,
                currency="usd",
                **item,
                idempotency_key=f"{key}-scope-{index}",
            )
        details = [
            ("Event details", snapshot["location"]),
            ("Design notes", snapshot["description"]),
            ("Terms", snapshot["terms"]),
        ]
        if part_index is not None:
            details.append(
                (
                    "Payment plan",
                    "; ".join(
                        f"{index + 1}. ${part['amount_cents'] / 100:.2f} due {part['due_date']}"
                        for index, part in enumerate(quote.installments)
                    ),
                )
            )
        if step == "amended":
            details.append(
                (
                    "Revised agreement",
                    f"Prior verified receipts less refunds: "
                    f"${quote.amendments[-1]['retained_paid_cents'] / 100:.2f}; "
                    f"remaining due: ${amount / 100:.2f}. Acceptance: "
                    f"{quote.amendments[-1]['acceptance_reference']}",
                )
            )
        for label, value in details:
            for index in range(0, len(value), 300):
                await asyncio.to_thread(
                    stripe.InvoiceItem.create,
                    customer=customer.id,
                    invoice=invoice.id,
                    amount=0,
                    currency="usd",
                    description=f"{label}: {value[index : index + 300]}",
                    idempotency_key=f"{key}-{label.lower().replace(' ', '-')}-{index // 300}",
                )
        if step != "full":
            await asyncio.to_thread(
                stripe.InvoiceItem.create,
                customer=customer.id,
                invoice=invoice.id,
                amount=amount,
                currency="usd",
                description=f"{snapshot['title']} — {payment_label} payment",
                idempotency_key=f"{key}-item",
            )
        invoice = await asyncio.to_thread(
            stripe.Invoice.finalize_invoice, invoice.id, idempotency_key=f"{key}-finalize"
        )
        if invoice.total != amount or invoice.currency != "usd":
            raise ValueError("Stripe invoice amount differs from the quote. Review in Stripe before retrying.")
        invoice = await asyncio.to_thread(stripe.Invoice.send_invoice, invoice.id, idempotency_key=f"{key}-send")
    except Exception:
        async with session_scope() as db:
            row = await db.scalar(
                select(WeddingInvoice).where(
                    WeddingInvoice.quote_id == quote_id,
                    WeddingInvoice.step == step,
                    WeddingInvoice.revision == revision,
                )
            )
            if row and row.status == "issuing":
                row.status = "review"
                quote = await db.get(WeddingQuote, quote_id)
                quote.status = "review"
                await db.commit()
        raise
    async with session_scope() as db:
        row = await db.scalar(
            select(WeddingInvoice)
            .where(
                WeddingInvoice.quote_id == quote_id, WeddingInvoice.step == step, WeddingInvoice.revision == revision
            )
            .with_for_update()
        )
        quote = await db.get(WeddingQuote, quote_id)
        row.stripe_invoice_id = invoice.id
        row.hosted_url = invoice.hosted_invoice_url or ""
        row.status = "sent"
        quote.stripe_customer_id = customer.id
        quote.status = (
            "amendment_sent"
            if step == "amended"
            else "balance_sent"
            if step == "balance"
            else "installment_sent"
            if part_index is not None and part_index > 0
            else "sent"
        )
        quote.activity = [
            *(quote.activity or []),
            dict(action=f"{step} invoice sent", invoice_id=invoice.id, at=datetime.now(UTC).isoformat()),
        ]
        await db.commit()
    return invoice.id


async def revise_wedding_invoice(quote_id: int, invoice_id: int, *, actor_id: int) -> None:
    """Void a known, still-open Stripe invoice; preserve its row before reissuing."""

    if not get_settings().stripe_secret_key:
        raise ValueError("Stripe is not configured.")
    stripe.api_key = get_settings().stripe_secret_key
    async with session_scope() as db:
        quote = await db.scalar(select(WeddingQuote).where(WeddingQuote.id == quote_id).with_for_update())
        row = await db.scalar(
            select(WeddingInvoice)
            .where(WeddingInvoice.id == invoice_id, WeddingInvoice.quote_id == quote_id)
            .with_for_update()
        )
        if not quote or not row or not row.stripe_invoice_id or row.status not in ("sent", "void", "review"):
            raise ValueError(
                "Only a known sent or verified void invoice can be revised. "
                "Investigate uncertain sends in Stripe first."
            )
        if quote.order_id or quote.status not in (
            "sent",
            "balance_sent",
            "installment_sent",
            "amendment_sent",
            "void",
            "deposit_paid",
            "review",
        ):
            raise ValueError("Reconcile the current payment state before revising this invoice.")
        active = (
            await db.scalars(
                select(WeddingInvoice).where(WeddingInvoice.quote_id == quote_id, WeddingInvoice.status == "sent")
            )
        ).all()
        if (row.status == "sent" and (len(active) != 1 or active[0].id != row.id)) or (row.status != "sent" and active):
            raise ValueError("More than one invoice is outstanding; review in Stripe.")
        if row.status in ("void", "review"):
            latest = await db.scalar(
                select(WeddingInvoice.id)
                .where(WeddingInvoice.quote_id == quote_id, WeddingInvoice.step == row.step)
                .order_by(WeddingInvoice.revision.desc())
            )
            if latest != row.id:
                raise ValueError("A newer invoice already exists for this payment.")
        try:
            remote = await asyncio.to_thread(stripe.Invoice.retrieve, row.stripe_invoice_id)
        except Exception:
            raise ValueError(
                "Could not verify the invoice in Stripe. Nothing was voided; retry only after checking Stripe."
            ) from None
        if remote.id != row.stripe_invoice_id or remote.currency != "usd" or remote.total != row.amount_cents:
            raise ValueError("Stripe does not confirm this invoice at the agreed amount. Reconcile first.")
        if row.status == "review" and remote.status == "open":
            row.status = "sent"
            quote.status = (
                "amendment_sent"
                if row.step == "amended"
                else "balance_sent"
                if row.step == "balance"
                else "installment_sent"
                if row.step.startswith("part_") and row.step != "part_01"
                else "sent"
            )
            quote.activity = [
                *(quote.activity or []),
                dict(
                    action="reviewed invoice still open",
                    invoice_id=row.stripe_invoice_id,
                    actor=actor_id,
                    at=datetime.now(UTC).isoformat(),
                ),
            ]
            await db.commit()
            return
        if row.status == "void":
            if remote.status != "void":
                raise ValueError("Stripe does not confirm this invoice was voided. Reconcile first.")
        elif row.status == "review":
            if remote.status != "void":
                raise ValueError("Stripe invoice is not confirmed void or open. Reconcile payment before proceeding.")
        else:
            if remote.status != "open":
                raise ValueError("Stripe does not confirm this invoice is open. Reconcile first.")
            try:
                voided = await asyncio.to_thread(
                    stripe.Invoice.void_invoice,
                    row.stripe_invoice_id,
                    idempotency_key=f"wedding-{quote_id}-void-{invoice_id}",
                )
                if voided.id != row.stripe_invoice_id or voided.status != "void":
                    raise RuntimeError("Stripe did not confirm the void")
            except Exception:
                row.status = "review"
                quote.status = "review"
                await db.commit()
                raise ValueError(
                    "The Stripe void outcome is uncertain. Review Stripe; do not send another invoice."
                ) from None
        row.status = "void"
        quote.status = (
            "review"
            if row.step == "amended"
            else "deposit_paid"
            if row.step == "balance"
            else "installment_paid"
            if row.step.startswith("part_") and row.step != "part_01"
            else "draft"
        )
        quote.activity = [
            *(quote.activity or []),
            dict(
                action="invoice voided for revision",
                invoice_id=row.stripe_invoice_id,
                invoice_row_id=row.id,
                actor=actor_id,
                at=datetime.now(UTC).isoformat(),
            ),
        ]
        await db.commit()


async def attach_reviewed_wedding_invoice(quote_id: int, invoice_id: int, remote_id: str, *, actor_id: int) -> None:
    """Recover the exact original Stripe invoice, including a verified paid one."""

    remote_id = remote_id.strip()
    if not remote_id.startswith("in_") or len(remote_id) > 255 or not get_settings().stripe_secret_key:
        raise ValueError("Enter a Stripe invoice ID and configure Stripe first.")
    stripe.api_key = get_settings().stripe_secret_key
    async with session_scope() as db:
        quote = await db.scalar(select(WeddingQuote).where(WeddingQuote.id == quote_id).with_for_update())
        row = await db.scalar(
            select(WeddingInvoice)
            .where(WeddingInvoice.id == invoice_id, WeddingInvoice.quote_id == quote_id)
            .with_for_update()
        )
        if not quote or not row or quote.status != "review" or row.status != "review" or row.stripe_invoice_id:
            raise ValueError("Only an uncertain invoice without a saved Stripe ID can be attached.")
        if await db.scalar(select(WeddingInvoice.id).where(WeddingInvoice.stripe_invoice_id == remote_id)):
            raise ValueError("This Stripe invoice is already attached to a wedding payment.")

        if await db.scalar(select(BouquetProposal.id).where(BouquetProposal.stripe_invoice_id == remote_id)):
            raise ValueError("This Stripe invoice already belongs to a bouquet proposal.")
        try:
            remote = await asyncio.to_thread(stripe.Invoice.retrieve, remote_id)
        except Exception:
            raise ValueError("Could not verify the invoice in Stripe. No payment state changed.") from None
        metadata = remote.get("metadata") or {}
        if (
            remote.id != remote_id
            or remote.status not in ("open", "paid", "void")
            or remote.currency != "usd"
            or remote.total != row.amount_cents
            or metadata.get("wedding_quote_id") != str(quote_id)
            or metadata.get("step") != row.step
            or metadata.get("revision", "1") != str(row.revision)
        ):
            raise ValueError(
                "Stripe does not confirm an invoice for this exact quote, step, revision and amount. Review manually."
            )
        if (
            remote.status == "paid"
            and (
                remote.amount_paid != row.amount_cents or remote.amount_remaining != 0 or remote.get("paid_out_of_band")
            )
        ) or (remote.status in ("open", "void") and remote.amount_paid != 0):
            raise ValueError("Invoice payment details do not match. Review Stripe manually.")
        row.stripe_invoice_id = remote.id
        row.hosted_url = remote.get("hosted_invoice_url") or ""
        row.status = "void" if remote.status == "void" else "sent"
        quote.stripe_customer_id = remote.customer
        quote.status = (
            (
                "review"
                if row.step == "amended"
                else "deposit_paid"
                if row.step == "balance"
                else "review"
                if row.step.startswith("part_") and row.step != "part_01"
                else "void"
            )
            if remote.status == "void"
            else (
                "amendment_sent"
                if row.step == "amended"
                else "balance_sent"
                if row.step == "balance"
                else "installment_sent"
                if row.step.startswith("part_") and row.step != "part_01"
                else "sent"
            )
        )
        quote.activity = [
            *(quote.activity or []),
            dict(
                action="reviewed invoice attached",
                invoice_id=remote_id,
                invoice_row_id=invoice_id,
                actor=actor_id,
                stripe_status=remote.status,
                at=datetime.now(UTC).isoformat(),
            ),
        ]
        await db.commit()
    if remote.status == "paid":
        event = dict(
            id=f"wedding-recover-{remote_id}-paid",
            type="invoice.paid",
            data={
                "object": dict(
                    id=remote.id,
                    currency=remote.currency,
                    total=remote.total,
                    amount_paid=remote.amount_paid,
                    amount_remaining=remote.amount_remaining,
                    status=remote.status,
                    paid_out_of_band=False,
                )
            },
        )
        outcome = await apply_wedding_invoice_event(event)
        if outcome not in ("applied", "ignored"):
            async with session_scope() as db:
                quote = await db.scalar(select(WeddingQuote).where(WeddingQuote.id == quote_id).with_for_update())
                row = await db.get(WeddingInvoice, invoice_id)
                if row.status == "sent":
                    row.status = "review"
                    quote.status = "review"
                    await db.commit()
            raise ValueError("Stripe reports payment, but local booking needs review. Do not send a new invoice.")


async def apply_wedding_invoice_event(event: dict) -> str:
    """Caller verifies the Stripe signature; only a fully paid invoice advances."""

    kind = event.get("type")
    obj = event.get("data", {}).get("object", {})
    invoice_id = obj.get("id")
    if not invoice_id or kind not in ("invoice.paid", "invoice.voided", "invoice.payment_failed"):
        return "review"
    order_id = None
    async with session_scope() as db:
        row = await db.scalar(
            select(WeddingInvoice).where(WeddingInvoice.stripe_invoice_id == invoice_id).with_for_update()
        )
        if not row:
            return "review"
        quote = await db.scalar(select(WeddingQuote).where(WeddingQuote.id == row.quote_id).with_for_update())
        event_id = event.get("id")
        if event_id and await db.scalar(select(StripeEvent.id).where(StripeEvent.event_id == event_id)):
            return "ignored"
        if kind == "invoice.paid":
            if row.status == "paid":
                return "ignored"
            if (
                row.status != "sent"
                or obj.get("currency") != "usd"
                or obj.get("total") != row.amount_cents
                or obj.get("amount_paid") != row.amount_cents
                or obj.get("amount_remaining") != 0
                or obj.get("paid_out_of_band")
                or obj.get("status") != "paid"
            ):
                return "review"
            part_index = int(row.step[5:]) - 1 if row.step.startswith("part_") and row.step[5:].isdigit() else None
            if part_index is not None:
                if (
                    quote.payment_mode != "installments"
                    or part_index >= len(quote.installments or [])
                    or row.amount_cents != quote.installments[part_index]["amount_cents"]
                    or quote.status != ("sent" if part_index == 0 else "installment_sent")
                ):
                    return "review"
            if row.step == "deposit" or (part_index is not None and part_index < len(quote.installments) - 1):
                if row.step == "deposit" and quote.status != "sent":
                    return "review"
                quote.status = "deposit_paid" if row.step == "deposit" else "installment_paid"
                inquiry = await db.get(Inquiry, quote.inquiry_id)
                inquiry.stage = "booked"
            else:
                if (
                    (row.step == "balance" and quote.status != "balance_sent")
                    or (row.step == "full" and quote.status != "sent")
                    or (row.step == "amended" and quote.status != "amendment_sent")
                    or (part_index is not None and part_index != len(quote.installments) - 1)
                ):
                    return "review"
                if row.step == "amended":
                    if not quote.amendments:
                        return "review"
                    previous = (
                        await db.scalars(
                            select(WeddingInvoice).where(
                                WeddingInvoice.quote_id == quote.id,
                                WeddingInvoice.status == "paid",
                                WeddingInvoice.id != row.id,
                            )
                        )
                    ).all()
                    if not previous:
                        return "review"
                    refunds = (
                        await db.scalars(
                            select(InvoiceRefund).where(
                                InvoiceRefund.wedding_invoice_id.in_([invoice.id for invoice in previous])
                            )
                        )
                    ).all()
                    if any(item.status != "succeeded" for item in refunds):
                        return "review"
                    retained = sum(invoice.amount_cents for invoice in previous) - sum(
                        item.amount_cents for item in refunds
                    )
                    amendment = quote.amendments[-1]
                    if (
                        retained != amendment["retained_paid_cents"]
                        or row.amount_cents + retained != amendment["draft"]["total_cents"]
                    ):
                        return "review"
                inquiry = await db.get(Inquiry, quote.inquiry_id)
                inquiry.stage = "booked"
                snapshot = quote.amendments[-1]["draft"] if row.step == "amended" else quote.snapshot
                order = Order(
                    customer_name=inquiry.name,
                    customer_email=inquiry.email,
                    customer_phone=inquiry.phone,
                    channel="retail",
                    status="paid",
                    payment_method="stripe_invoice",
                    payment_reference=invoice_id,
                    fulfillment="delivery",
                    delivery_address=snapshot["location"],
                    notes=f"Wedding/event quote #{quote.id} — {snapshot['title']}",
                )
                db.add(order)
                await db.flush()
                for line in snapshot["lines"]:
                    db.add(
                        OrderItem(
                            order_id=order.id,
                            listing_id=None,
                            name_snapshot=line["name"],
                            price_snapshot=Decimal(line["unit_cents"]) / 100,
                            quantity=line["quantity"],
                        )
                    )
                db.add_all(
                    OrderNotification(order_id=order.id, recipient=recipient) for recipient in ("customer", "farm")
                )
                quote.order_id = order.id
                quote.status = "paid"
                order_id = order.id
            row.status = "paid"
            row.paid_at = datetime.now(UTC)
        elif kind == "invoice.voided":
            if row.status == "void":
                return "ignored"
            if row.status != "sent":
                return "review"
            row.status = "void"
            quote.status = (
                "review"
                if row.step == "amended"
                else "deposit_paid"
                if row.step == "balance"
                else "review"
                if row.step.startswith("part_") and row.step != "part_01"
                else "void"
            )
        elif kind == "invoice.payment_failed":
            pass  # Outstanding invoice remains payable; do not mark booked/paid.
        else:
            return "review"
        quote.activity = [
            *(quote.activity or []),
            dict(action=kind, invoice_id=invoice_id, at=datetime.now(UTC).isoformat()),
        ]
        if event_id:
            db.add(StripeEvent(event_id=event_id, order_id=order_id, event_type=kind, outcome="applied"))
        await db.commit()
    if order_id:
        await deliver_notifications(order_id)
    return "applied"


async def reconcile_wedding_invoice(invoice_id: int) -> str:
    """Refresh a persisted invoice from Stripe after a missed webhook."""

    if not get_settings().stripe_secret_key:
        raise ValueError("Stripe is not configured.")
    stripe.api_key = get_settings().stripe_secret_key
    async with session_scope() as db:
        row = await db.get(WeddingInvoice, invoice_id)
        if not row or not row.stripe_invoice_id:
            raise ValueError("The invoice is not recorded locally; review Stripe manually.")
        remote_id = row.stripe_invoice_id
    remote = await asyncio.to_thread(stripe.Invoice.retrieve, remote_id)
    if remote.id != remote_id:
        raise ValueError("Stripe returned a different invoice; review manually.")
    if remote.status not in ("paid", "void"):
        return "unchanged"
    obj = dict(
        id=remote.id,
        total=remote.total,
        currency=remote.currency,
        amount_paid=remote.amount_paid,
        amount_remaining=remote.amount_remaining,
        status=remote.status,
        paid_out_of_band=remote.get("paid_out_of_band", False),
    )
    return await apply_wedding_invoice_event(
        dict(
            id=f"wedding-reconcile-{remote_id}-{remote.status}",
            type="invoice.paid" if remote.status == "paid" else "invoice.voided",
            data={"object": obj},
        )
    )
