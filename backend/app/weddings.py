"""Wedding quote invoices: full upfront or separate deposit and balance."""
from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .db import session_scope
from .models import Inquiry, Order, OrderItem, OrderNotification, StripeEvent, WeddingInvoice, WeddingQuote
from .proposals import cents
from .settings import get_settings


EASTERN = ZoneInfo("America/New_York")


def eastern_today() -> date:
    return datetime.now(EASTERN).date()


def validate_schedule(form, payment_mode: str, *, today: date | None = None) -> dict:
    """Keep agreed invoice dates separate from quote amounts and free-form copy."""
    today = today or eastern_today()
    initial_mode = str(form.get("initial_send_mode", "manual"))
    balance_mode = str(form.get("balance_send_mode", "manual")) if payment_mode == "deposit" else "manual"
    if initial_mode not in ("manual", "automatic") or balance_mode not in ("manual", "automatic"):
        raise ValueError("Choose manual or automatic invoice sending.")
    def chosen_date(name):
        raw = str(form.get(name, "")).strip()
        try:
            return date.fromisoformat(raw) if raw else None
        except ValueError:
            raise ValueError(f"Enter a valid {name.replace('_', ' ')}.") from None
    first_send = chosen_date("initial_send_date") if initial_mode == "automatic" else None
    first_due = chosen_date("initial_due_date")
    balance_send = chosen_date("balance_send_date") if balance_mode == "automatic" else None
    balance_due = chosen_date("balance_due_date") if payment_mode == "deposit" else None
    if initial_mode == "automatic" and not first_send:
        raise ValueError("Choose when to send the first invoice automatically.")
    if payment_mode == "deposit" and balance_mode == "automatic" and not balance_send:
        raise ValueError("Choose when to send the balance invoice automatically.")
    if initial_mode == "automatic" and not first_due:
        raise ValueError("Choose a due date for the scheduled first invoice.")
    if payment_mode == "deposit" and balance_mode == "automatic" and not balance_due:
        raise ValueError("Choose a due date for the scheduled balance invoice.")
    if payment_mode == "deposit" and balance_due and not first_due:
        raise ValueError("Set the deposit due date before choosing a balance due date.")
    if (first_send and first_send < today) or (balance_send and balance_send < today):
        raise ValueError("Scheduled sending cannot start in the past.")
    if (first_due and first_due < (first_send or today)) or (balance_due and balance_due < (balance_send or today)):
        raise ValueError("Each due date must be on or after its sending date and not in the past.")
    if payment_mode == "deposit" and first_due and balance_due and balance_due < first_due:
        raise ValueError("Balance must be due on or after the deposit due date.")
    return dict(initial_send_mode=initial_mode, initial_send_date=first_send,
                initial_due_date=first_due, balance_send_mode=balance_mode,
                balance_send_date=balance_send, balance_due_date=balance_due)


def installment_step(index: int) -> str:
    return f"part_{index + 1:02d}"


def validate_installments(form, total_cents: int, *, today: date | None = None) -> list[dict]:
    """Validate exact integer-cent sum and chronological per-payment terms."""
    today = today or eastern_today()
    raw_ids = str(form.get("installment_ids", "")).strip()
    if raw_ids:
        tokens = raw_ids.split(",")
        if not all(token.isdigit() and 1 <= int(token) <= 100000 for token in tokens):
            raise ValueError("Installment identifiers are invalid.")
        indexes = [int(token) for token in tokens]
    else:
        # Accept older forms that posted fixed numbered amount fields.
        indexes = sorted(int(match.group(1)) for key in form.keys()
                         if (match := re.fullmatch(r"installment_amount_(\d+)", str(key))))
    if len(indexes) != len(set(indexes)) or len(indexes) > 200:
        raise ValueError("Add no more than 200 distinct installments.")
    parts = []
    previous_due = None
    previous_send = None
    for index in indexes:
        kind = str(form.get(f"installment_type_{index}", "amount"))
        if kind not in ("amount", "percent"):
            raise ValueError("Choose a dollar amount or percentage for each installment.")
        raw_amount = str(form.get(f"installment_amount_{index}", "")).strip()
        raw_percent = str(form.get(f"installment_percent_{index}", "")).strip()
        if kind == "percent":
            try:
                percent = Decimal(raw_percent)
            except InvalidOperation:
                raise ValueError("Enter a valid installment percentage.") from None
            if not percent.is_finite() or not 0 < percent <= 100 or percent.as_tuple().exponent < -2:
                raise ValueError("Enter a percentage between 0 and 100 with at most two decimals.")
            amount = int((Decimal(total_cents) * percent / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        else:
            percent = None
            amount = cents(raw_amount)
        mode = str(form.get(f"installment_send_mode_{index}", "manual"))
        if mode not in ("manual", "automatic") or amount < 50:
            raise ValueError("Every installment must be at least $0.50 with a valid sending mode.")
        def parse_date(field):
            raw = str(form.get(f"installment_{field}_{index}", "")).strip()
            try:
                return date.fromisoformat(raw) if raw else None
            except ValueError:
                raise ValueError(f"Enter a valid installment {field.replace('_', ' ')}.") from None
        send = parse_date("send_date") if mode == "automatic" else None
        due = parse_date("due_date")
        if not due or (mode == "automatic" and not send):
            raise ValueError("Each installment needs a due date; automatic sending also needs a send date.")
        if (send and send < today) or due < (send or today):
            raise ValueError("Installment dates cannot be in the past or due before sending.")
        if previous_due and due <= previous_due:
            raise ValueError("Installment due dates must increase in order.")
        if previous_send and send and send < previous_send:
            raise ValueError("Installment send dates must not move backward.")
        parts.append(dict(amount_cents=amount, amount_type=kind,
                          percent=str(percent) if percent is not None else None, send_mode=mode,
                          send_date=send.isoformat() if send else None, due_date=due.isoformat()))
        previous_due, previous_send = due, send or previous_send
    if not 2 <= len(parts) <= 200:
        raise ValueError("Enter between two and 200 installments.")
    if all(part["amount_type"] == "percent" for part in parts) and sum(
            Decimal(part["percent"]) for part in parts) == 100:
        # Assign rounding pennies to the final payment, without changing the agreed total.
        parts[-1]["amount_cents"] = total_cents - sum(part["amount_cents"] for part in parts[:-1])
        if parts[-1]["amount_cents"] < 50:
            raise ValueError("Every installment must be at least $0.50 after rounding.")
    actual_cents = sum(part["amount_cents"] for part in parts)
    if actual_cents != total_cents:
        difference = total_cents - actual_cents
        action = "Add" if difference > 0 else "Reduce payments by"
        raise ValueError(f"Installments must total exactly ${total_cents / 100:.2f}. "
                         f"Current payments total ${actual_cents / 100:.2f}. "
                         f"{action} ${abs(difference) / 100:.2f}{' to the payments' if difference > 0 else ''}.")
    return parts


def due_timestamp(day: date) -> int:
    """Stripe due_date is an epoch second; show end-of-day in Eastern time."""
    return int(datetime.combine(day, time(23, 59, 59), EASTERN).timestamp())


def validate_quote(form) -> tuple[dict, str, int]:
    title = str(form.get("title", "")).strip()
    description = str(form.get("description", "")).strip()
    terms = str(form.get("terms", "")).strip()
    location = str(form.get("location", "")).strip()
    mode = str(form.get("payment_mode", ""))
    if not title or not description or not terms or not location or mode not in ("full", "deposit", "installments"):
        raise ValueError("Title, description, terms, event location and payment mode are required.")
    if any(len(value) > limit for value, limit in ((title, 160), (description, 2000), (terms, 2000), (location, 500))):
        raise ValueError("Quote text is too long.")
    raw_ids = str(form.get("line_ids", "")).strip()
    if raw_ids:
        tokens = raw_ids.split(",")
        if not all(token.isdigit() and 1 <= int(token) <= 100000 for token in tokens):
            raise ValueError("Quote line identifiers are invalid.")
        indexes = [int(token) for token in tokens]
    else:
        indexes = sorted(int(match.group(1)) for key in form.keys()
                         if (match := re.fullmatch(r"name_(\d+)", str(key))))
    if len(indexes) != len(set(indexes)) or len(indexes) > 200:
        raise ValueError("Add no more than 200 distinct quote lines.")
    lines = []
    for index in indexes:
        name = str(form.get(f"name_{index}", "")).strip()
        if not name:
            if str(form.get(f"quantity_{index}", "")).strip() or str(form.get(f"price_{index}", "")).strip():
                raise ValueError("Name each quote line that has a quantity or price.")
            continue
        try:
            quantity = int(str(form.get(f"quantity_{index}", "")))
        except ValueError:
            raise ValueError("Enter a valid line quantity.") from None
        if len(name) > 160 or not 1 <= quantity <= 9999:
            raise ValueError("Each line needs a name and a quantity from 1–9999.")
        lines.append(dict(name=name, quantity=quantity, unit_cents=cents(str(form.get(f"price_{index}", "")))))
    if not lines:
        raise ValueError("Add at least one itemized service or arrangement.")
    total = sum(line["unit_cents"] * line["quantity"] for line in lines)
    if not 50 <= total <= 99999999:
        raise ValueError("Total must be between $0.50 and $999,999.99.")
    deposit = cents(str(form.get("deposit", ""))) if mode == "deposit" else 0
    if mode == "deposit" and not 50 <= deposit <= total - 50:
        raise ValueError("Deposit and remaining balance must each be at least $0.50.")
    return dict(title=title, description=description, terms=terms, location=location,
                lines=lines, total_cents=total), mode, deposit


async def approve_wedding_schedule(quote_id: int) -> None:
    """Owner approval freezes the quote before an independent job can send it."""
    async with session_scope() as db:
        quote = await db.scalar(select(WeddingQuote).where(WeddingQuote.id == quote_id).with_for_update())
        if not quote or quote.status != "draft" or quote.initial_send_mode != "automatic" or not quote.initial_send_date:
            raise ValueError("Save an automatic sending date on a draft quote first.")
        if quote.initial_send_date < eastern_today() or not quote.initial_due_date or quote.initial_due_date < quote.initial_send_date:
            raise ValueError("The sending or due date is no longer valid. Edit the quote first.")
        if quote.payment_mode == "installments":
            if not quote.installments or date.fromisoformat(quote.installments[0]["due_date"]) < eastern_today():
                raise ValueError("The first installment due date has passed. Edit the quote first.")
        else:
            validate_schedule(dict(
                initial_send_mode=quote.initial_send_mode, initial_send_date=quote.initial_send_date.isoformat(),
                initial_due_date=quote.initial_due_date.isoformat(), balance_send_mode=quote.balance_send_mode,
                balance_send_date=quote.balance_send_date.isoformat() if quote.balance_send_date else "",
                balance_due_date=quote.balance_due_date.isoformat() if quote.balance_due_date else "",
            ), quote.payment_mode)
        if "total_cents" not in (quote.draft or {}):
            raise ValueError("Complete the itemized quote before scheduling.")
        quote.snapshot = quote.draft
        quote.status = "scheduled"
        quote.activity = [*(quote.activity or []), dict(action="first invoice scheduled", at=datetime.now(timezone.utc).isoformat(), send_date=quote.initial_send_date.isoformat())]
        await db.commit()


async def next_installment_index(db, quote: WeddingQuote) -> int | None:
    rows = (await db.scalars(select(WeddingInvoice).where(
        WeddingInvoice.quote_id == quote.id, WeddingInvoice.step.like("part_%")
    ).order_by(WeddingInvoice.id))).all()
    if any(row.status != "paid" or row.step != installment_step(index) for index, row in enumerate(rows)):
        return None
    return len(rows) if len(rows) < len(quote.installments or []) else None


async def run_wedding_schedule(*, apply: bool = False, today: date | None = None) -> list[str]:
    """One bounded run; a platform scheduler must invoke it repeatedly."""
    today = today or eastern_today()
    async with session_scope() as db:
        initial_ids = (await db.scalars(select(WeddingQuote.id).where(
            WeddingQuote.status == "scheduled", WeddingQuote.initial_send_mode == "automatic",
            WeddingQuote.initial_send_date <= today).order_by(WeddingQuote.id).limit(100))).all()
        balance_ids = (await db.scalars(select(WeddingQuote.id).where(
            WeddingQuote.status == "deposit_paid", WeddingQuote.balance_send_mode == "automatic",
            WeddingQuote.balance_send_date <= today).order_by(WeddingQuote.id).limit(100))).all()
        part_ids = []
        offset = 0
        while len(part_ids) < 100:
            awaiting_parts = (await db.scalars(select(WeddingQuote).where(
                WeddingQuote.status == "installment_paid", WeddingQuote.payment_mode == "installments"
            ).order_by(WeddingQuote.id).offset(offset).limit(100))).all()
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
    for quote_id, step in [*((id, "initial") for id in initial_ids), *((id, "balance") for id in balance_ids), *part_ids]:
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
    import stripe
    settings = get_settings()
    if not settings.stripe_secret_key or not settings.stripe_webhook_secret:
        raise ValueError("Stripe invoices and a signed webhook must be configured first.")
    part_index = int(step[5:]) - 1 if step.startswith("part_") and step[5:].isdigit() else None
    if step not in ("full", "deposit", "balance") and (part_index is None or part_index < 0 or step != installment_step(part_index)):
        raise ValueError("Unknown invoice step.")
    stripe.api_key = settings.stripe_secret_key
    async with session_scope() as db:
        quote = await db.scalar(select(WeddingQuote).where(WeddingQuote.id == quote_id).with_for_update())
        if not quote:
            raise ValueError("This invoice cannot be sent in the current state.")
        if part_index is not None:
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
                step != "balance" and (quote.status != ("scheduled" if scheduled else "draft") or quote.payment_mode != step)
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
        snapshot = quote.snapshot if step == "balance" or (part_index is not None and part_index > 0) else quote.draft
        amount = (quote.installments[part_index]["amount_cents"] if part_index is not None else
                  snapshot["total_cents"] - quote.deposit_cents if step == "balance" else
                  quote.deposit_cents if step == "deposit" else snapshot["total_cents"])
        row = WeddingInvoice(quote_id=quote_id, step=step, status="issuing", amount_cents=amount)
        db.add(row)
        if step != "balance" and part_index in (None, 0):
            quote.snapshot = quote.draft
        quote.status = "issuing"
        await db.commit()
        email, name, customer_id = inquiry.email, inquiry.name, quote.stripe_customer_id
    key = f"wedding-{quote_id}-{step}"
    try:
        customer = await asyncio.to_thread(stripe.Customer.retrieve, customer_id) if customer_id else await asyncio.to_thread(
            stripe.Customer.create, email=email, name=name, idempotency_key=f"{key}-customer")
        payment_label = f"Installment {part_index + 1} of {len(quote.installments)}" if part_index is not None else step.capitalize()
        memo = (f"{snapshot['title']}\nQuote total: ${snapshot['total_cents'] / 100:.2f}; "
                f"{payment_label}: ${amount / 100:.2f}\nEvent: {snapshot['location']}")
        if len(memo) > 500:
            memo = memo[:497] + "..."
        invoice = await asyncio.to_thread(stripe.Invoice.create, customer=customer.id,
            collection_method="send_invoice", **({"due_date": due_timestamp(due_date)} if due_date else {"days_until_due": 7}), auto_advance=False,
            pending_invoice_items_behavior="exclude", metadata={"wedding_quote_id": str(quote_id), "step": step},
            description=memo,
            idempotency_key=f"{key}-invoice")
        for index, line in enumerate(snapshot["lines"]):
            if step == "full":
                item = dict(unit_amount_decimal=str(line["unit_cents"]), quantity=line["quantity"],
                            description=line["name"])
            else:
                item = dict(amount=0, description=(
                    f"Quote scope (included in ${snapshot['total_cents'] / 100:.2f} total): "
                    f"{line['quantity']} × {line['name']} — ${line['quantity'] * line['unit_cents'] / 100:.2f}"))
            await asyncio.to_thread(stripe.InvoiceItem.create, customer=customer.id, invoice=invoice.id,
                                    currency="usd", **item, idempotency_key=f"{key}-scope-{index}")
        details = [("Event details", snapshot["location"]),
                   ("Design notes", snapshot["description"]), ("Terms", snapshot["terms"])]
        if part_index is not None:
            details.append(("Payment plan", "; ".join(
                f"{index + 1}. ${part['amount_cents'] / 100:.2f} due {part['due_date']}"
                for index, part in enumerate(quote.installments))))
        for label, value in details:
            for index in range(0, len(value), 300):
                await asyncio.to_thread(stripe.InvoiceItem.create, customer=customer.id, invoice=invoice.id,
                    amount=0, currency="usd", description=f"{label}: {value[index:index + 300]}",
                    idempotency_key=f"{key}-{label.lower().replace(' ', '-')}-{index // 300}")
        if step != "full":
            await asyncio.to_thread(stripe.InvoiceItem.create, customer=customer.id, invoice=invoice.id,
                amount=amount, currency="usd", description=f"{snapshot['title']} — {payment_label} payment",
                idempotency_key=f"{key}-item")
        invoice = await asyncio.to_thread(stripe.Invoice.finalize_invoice, invoice.id, idempotency_key=f"{key}-finalize")
        if invoice.total != amount or invoice.currency != "usd":
            raise ValueError("Stripe invoice amount differs from the quote. Review in Stripe before retrying.")
        invoice = await asyncio.to_thread(stripe.Invoice.send_invoice, invoice.id, idempotency_key=f"{key}-send")
    except Exception:
        async with session_scope() as db:
            row = await db.scalar(select(WeddingInvoice).where(WeddingInvoice.quote_id == quote_id, WeddingInvoice.step == step))
            if row and row.status == "issuing":
                row.status = "review"
                quote = await db.get(WeddingQuote, quote_id)
                quote.status = "review"
                await db.commit()
        raise
    async with session_scope() as db:
        row = await db.scalar(select(WeddingInvoice).where(WeddingInvoice.quote_id == quote_id, WeddingInvoice.step == step).with_for_update())
        quote = await db.get(WeddingQuote, quote_id)
        row.stripe_invoice_id = invoice.id
        row.hosted_url = invoice.hosted_invoice_url or ""
        row.status = "sent"
        quote.stripe_customer_id = customer.id
        quote.status = "balance_sent" if step == "balance" else "installment_sent" if part_index is not None and part_index > 0 else "sent"
        quote.activity = [*(quote.activity or []), dict(action=f"{step} invoice sent", invoice_id=invoice.id, at=datetime.now(timezone.utc).isoformat())]
        await db.commit()
    return invoice.id


async def apply_wedding_invoice_event(event: dict) -> str:
    """Caller verifies the Stripe signature; only a fully paid invoice advances."""
    from .payments import deliver_notifications
    kind = event.get("type")
    obj = event.get("data", {}).get("object", {})
    invoice_id = obj.get("id")
    if not invoice_id or kind not in ("invoice.paid", "invoice.voided", "invoice.payment_failed"):
        return "review"
    order_id = None
    async with session_scope() as db:
        row = await db.scalar(select(WeddingInvoice).where(WeddingInvoice.stripe_invoice_id == invoice_id).with_for_update())
        if not row:
            return "review"
        quote = await db.scalar(select(WeddingQuote).where(WeddingQuote.id == row.quote_id).with_for_update())
        event_id = event.get("id")
        if event_id and await db.scalar(select(StripeEvent.id).where(StripeEvent.event_id == event_id)):
            return "ignored"
        if kind == "invoice.paid":
            if row.status == "paid":
                return "ignored"
            if (row.status != "sent" or obj.get("currency") != "usd" or obj.get("total") != row.amount_cents
                or obj.get("amount_paid") != row.amount_cents or obj.get("amount_remaining") != 0
                or obj.get("paid_out_of_band") or obj.get("status") != "paid"):
                return "review"
            part_index = int(row.step[5:]) - 1 if row.step.startswith("part_") and row.step[5:].isdigit() else None
            if part_index is not None:
                if (quote.payment_mode != "installments" or part_index >= len(quote.installments or [])
                    or row.amount_cents != quote.installments[part_index]["amount_cents"]
                    or quote.status != ("sent" if part_index == 0 else "installment_sent")):
                    return "review"
            if row.step == "deposit" or (part_index is not None and part_index < len(quote.installments) - 1):
                if row.step == "deposit" and quote.status != "sent":
                    return "review"
                quote.status = "deposit_paid" if row.step == "deposit" else "installment_paid"
                inquiry = await db.get(Inquiry, quote.inquiry_id)
                inquiry.stage = "booked"
            else:
                if (row.step == "balance" and quote.status != "balance_sent") or (
                    row.step == "full" and quote.status != "sent") or (
                    part_index is not None and part_index != len(quote.installments) - 1):
                    return "review"
                inquiry = await db.get(Inquiry, quote.inquiry_id)
                inquiry.stage = "booked"
                snapshot = quote.snapshot
                order = Order(customer_name=inquiry.name, customer_email=inquiry.email, customer_phone=inquiry.phone,
                              channel="retail", status="paid", payment_method="stripe_invoice",
                              payment_reference=invoice_id, fulfillment="delivery", delivery_address=snapshot["location"],
                              notes=f"Wedding/event quote #{quote.id} — {snapshot['title']}")
                db.add(order)
                await db.flush()
                for line in snapshot["lines"]:
                    db.add(OrderItem(order_id=order.id, listing_id=None, name_snapshot=line["name"],
                                     price_snapshot=Decimal(line["unit_cents"]) / 100, quantity=line["quantity"]))
                db.add_all(OrderNotification(order_id=order.id, recipient=recipient) for recipient in ("customer", "farm"))
                quote.order_id = order.id
                quote.status = "paid"
                order_id = order.id
            row.status = "paid"
            row.paid_at = datetime.now(timezone.utc)
        elif kind == "invoice.voided":
            if row.status == "void":
                return "ignored"
            if row.status != "sent":
                return "review"
            row.status = "void"
            quote.status = "deposit_paid" if row.step == "balance" else "review" if row.step.startswith("part_") and row.step != "part_01" else "void"
        elif kind == "invoice.payment_failed":
            pass  # Outstanding invoice remains payable; do not mark booked/paid.
        else:
            return "review"
        quote.activity = [*(quote.activity or []), dict(action=kind, invoice_id=invoice_id, at=datetime.now(timezone.utc).isoformat())]
        if event_id:
            db.add(StripeEvent(event_id=event_id, order_id=order_id, event_type=kind, outcome="applied"))
        await db.commit()
    if order_id:
        await deliver_notifications(order_id)
    return "applied"


async def reconcile_wedding_invoice(invoice_id: int) -> str:
    """Refresh a persisted invoice from Stripe after a missed webhook."""
    import stripe
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
    obj = dict(id=remote.id, total=remote.total, currency=remote.currency,
               amount_paid=remote.amount_paid, amount_remaining=remote.amount_remaining,
               status=remote.status, paid_out_of_band=remote.get("paid_out_of_band", False))
    return await apply_wedding_invoice_event(dict(
        id=f"wedding-reconcile-{remote_id}-{remote.status}",
        type="invoice.paid" if remote.status == "paid" else "invoice.voided",
        data={"object": obj}))
