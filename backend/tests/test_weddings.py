from types import SimpleNamespace
from datetime import timedelta

import pytest
import stripe
from sqlalchemy import select

from app.admin import CSRF_COOKIE
from app.auth import hash_password
from app.db import session_scope
from app.models import Inquiry, Order, OrderItem, User, WeddingInvoice, WeddingQuote
from app.server import app
from app.settings import get_settings
from app.weddings import (apply_wedding_invoice_event, approve_wedding_schedule, due_timestamp,
                          eastern_today, run_wedding_schedule, send_wedding_invoice,
                          validate_installments, validate_quote, validate_schedule)


def form(mode="deposit", deposit="30.00"):
    return dict(title="Wedding flowers", description="Garden design", terms="Seasonal substitutions",
                location="September 18, Green Barn", payment_mode=mode, deposit=deposit,
                name_1="Ceremony flowers", quantity_1="2", price_1="25.00",
                name_2="Design labor", quantity_2="1", price_2="10.00")


def paid(invoice_id, amount, event_id):
    return dict(id=event_id, type="invoice.paid", data={"object": dict(
        id=invoice_id, currency="usd", total=amount, amount_paid=amount,
        amount_remaining=0, status="paid", paid_out_of_band=False)})


def mock_stripe(monkeypatch, amounts):
    settings = get_settings()
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_mock")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_mock")
    monkeypatch.setattr(stripe.Customer, "create", lambda **kwargs: SimpleNamespace(id="cus_wedding"))
    monkeypatch.setattr(stripe.Customer, "retrieve", lambda *args: SimpleNamespace(id="cus_wedding"))
    monkeypatch.setattr(stripe.Invoice, "create", lambda **kwargs: SimpleNamespace(id=f"in_{kwargs['metadata']['step']}"))
    monkeypatch.setattr(stripe.InvoiceItem, "create", lambda **kwargs: SimpleNamespace(id="ii_1"))
    monkeypatch.setattr(stripe.Invoice, "finalize_invoice", lambda invoice_id, **kwargs: SimpleNamespace(
        id=invoice_id, total=amounts[invoice_id], currency="usd"))
    monkeypatch.setattr(stripe.Invoice, "send_invoice", lambda invoice_id, **kwargs: SimpleNamespace(
        id=invoice_id, hosted_invoice_url=f"https://invoice.stripe.com/{invoice_id}"))


def test_quote_validation_and_schedule():
    snapshot, mode, deposit = validate_quote(form())
    assert (snapshot["total_cents"], mode, deposit) == (6000, "deposit", 3000)
    assert validate_quote(form(mode="full"))[2] == 0
    for amount in ("NaN", "60.00", "59.99", "0.01"):
        with pytest.raises(ValueError):
            validate_quote(form(deposit=amount))


def test_dynamic_quote_lines_can_exceed_the_old_fixed_limit():
    fields = form(mode="full")
    fields["line_ids"] = "1,3,4,5,6,7,8,9"
    fields.pop("name_2")
    for index in (3, 4, 5, 6, 7, 8, 9):
        fields[f"name_{index}"] = f"Service {index}"
        fields[f"quantity_{index}"] = "1"
        fields[f"price_{index}"] = "1.00"
    draft, _, _ = validate_quote(fields)
    assert len(draft["lines"]) == 8
    assert draft["total_cents"] == 5700
    fields["line_ids"] = "1,1"
    with pytest.raises(ValueError, match="distinct"):
        validate_quote(fields)
    fields["line_ids"] = ",".join(str(index) for index in range(1, 202))
    with pytest.raises(ValueError, match="200"):
        validate_quote(fields)


def installment_form(today):
    fields = form(mode="installments")
    for index, amount in enumerate(("10.00", "20.00", "30.00"), start=1):
        fields[f"installment_amount_{index}"] = amount
        fields[f"installment_send_mode_{index}"] = "manual" if index == 2 else "automatic"
        fields[f"installment_due_date_{index}"] = (today + timedelta(days=index * 7)).isoformat()
        if index != 2:
            fields[f"installment_send_date_{index}"] = (today + timedelta(days=(index - 1) * 7)).isoformat()
    return fields


def test_installments_must_sum_exactly_and_have_increasing_dates():
    today = eastern_today()
    draft, mode, deposit = validate_quote(installment_form(today))
    assert mode == "installments" and deposit == 0
    parts = validate_installments(installment_form(today), draft["total_cents"])
    assert len(parts) == 3 and sum(p["amount_cents"] for p in parts) == 6000
    wrong = installment_form(today)
    wrong["installment_amount_3"] = "29.99"
    with pytest.raises(ValueError, match="exactly"):
        validate_installments(wrong, draft["total_cents"])
    wrong = installment_form(today)
    wrong["installment_due_date_2"] = wrong["installment_due_date_1"]
    with pytest.raises(ValueError, match="increase"):
        validate_installments(wrong, draft["total_cents"])
    manual = installment_form(today)
    manual["installment_send_date_2"] = "not-a-date"
    assert validate_installments(manual, draft["total_cents"])[1]["send_date"] is None


def test_dynamic_installments_and_percentages_with_rounding():
    today = eastern_today()
    mixed = {"installment_ids": "1,3", "installment_type_1": "percent", "installment_percent_1": "25",
             "installment_amount_3": "75.00", "installment_due_date_1": (today + timedelta(days=1)).isoformat(),
             "installment_due_date_3": (today + timedelta(days=2)).isoformat()}
    assert [part["amount_cents"] for part in validate_installments(mixed, 10000, today=today)] == [2500, 7500]
    mixed["installment_amount_3"] = "74.99"
    with pytest.raises(ValueError, match="exactly"):
        validate_installments(mixed, 10000, today=today)
    # Deleted row 2 is ignored; add seven percentage rows beyond the old six-payment limit.
    fields = {"installment_ids": "1,3,9,11,12,13,14"}
    percentages = ("20", "20", "20", "10", "10", "10", "10")
    for position, (index, percent) in enumerate(zip((1, 3, 9, 11, 12, 13, 14), percentages), start=1):
        fields.update({f"installment_type_{index}": "percent", f"installment_percent_{index}": percent,
                       f"installment_amount_{index}": "not-a-dollar",
                       f"installment_due_date_{index}": (today + timedelta(days=position)).isoformat()})
    parts = validate_installments(fields, 10001, today=today)
    assert len(parts) == 7 and sum(part["amount_cents"] for part in parts) == 10001
    assert parts[-1]["amount_cents"] == 1001
    assert parts[0]["percent"] == "20" and parts[0]["amount_type"] == "percent"
    fields["installment_percent_14"] = "9"
    with pytest.raises(ValueError, match="exactly"):
        validate_installments(fields, 10001, today=today)
    fields["installment_ids"] = "1,1"
    with pytest.raises(ValueError, match="distinct"):
        validate_installments(fields, 10001, today=today)
    fields["installment_ids"] = ",".join(str(index) for index in range(1, 202))
    with pytest.raises(ValueError, match="200"):
        validate_installments(fields, 10001, today=today)


@pytest.mark.asyncio
async def test_three_installments_wait_for_each_payment_and_create_one_order(monkeypatch):
    from app import weddings
    today = eastern_today()
    draft, mode, deposit = validate_quote(installment_form(today))
    parts = validate_installments(installment_form(today), draft["total_cents"])
    mock_stripe(monkeypatch, {"in_part_01": 1000, "in_part_02": 2000, "in_part_03": 3000})
    invoice_payloads, invoice_lines = [], []
    def create_invoice(**kwargs):
        invoice_payloads.append(kwargs)
        return SimpleNamespace(id=f"in_{kwargs['metadata']['step']}")
    def create_line(**kwargs):
        invoice_lines.append(kwargs)
        return SimpleNamespace(id=f"ii_{len(invoice_lines)}")
    monkeypatch.setattr(stripe.Invoice, "create", create_invoice)
    monkeypatch.setattr(stripe.InvoiceItem, "create", create_line)
    async with session_scope() as db:
        inquiry = Inquiry(kind="wedding", name="Ava", email="ava@example.com")
        db.add(inquiry)
        await db.flush()
        quote = WeddingQuote(inquiry_id=inquiry.id, draft=draft, snapshot={}, payment_mode=mode,
                             deposit_cents=deposit, installments=parts, activity=[],
                             initial_send_mode="automatic", initial_send_date=today,
                             initial_due_date=today + timedelta(days=7))
        db.add(quote)
        await db.commit()
        quote_id = quote.id
    await approve_wedding_schedule(quote_id)
    assert await run_wedding_schedule(apply=True) == [f"Wedding quote #{quote_id}: sent part_01 invoice in_part_01"]
    assert len(invoice_payloads[0]["description"]) <= 500
    assert invoice_payloads[0]["due_date"] == due_timestamp(today + timedelta(days=7))
    assert sum(line.get("amount", 0) for line in invoice_lines) == 1000
    assert sum("Quote scope" in line["description"] for line in invoice_lines) == len(draft["lines"])
    assert any(line["description"].startswith("Payment plan:") for line in invoice_lines)
    with pytest.raises(ValueError, match="previous"):
        await send_wedding_invoice(quote_id, "part_02")
    assert await apply_wedding_invoice_event(paid("in_part_01", 1000, "evt_part_01")) == "applied"
    async with session_scope() as db:
        assert (await db.get(WeddingQuote, quote_id)).status == "installment_paid"
        assert (await db.scalars(select(Order))).all() == []
    assert await run_wedding_schedule(apply=True) == []  # part 2 needs owner confirmation
    assert await send_wedding_invoice(quote_id, "part_02") == "in_part_02"
    assert await apply_wedding_invoice_event(paid("in_part_02", 2000, "evt_part_02")) == "applied"
    assert await run_wedding_schedule(apply=True) == []  # automatic part 3 date not reached
    monkeypatch.setattr(weddings, "eastern_today", lambda: today + timedelta(days=14))
    assert await run_wedding_schedule(apply=True, today=today + timedelta(days=14)) == [
        f"Wedding quote #{quote_id}: sent part_03 invoice in_part_03"]
    assert await apply_wedding_invoice_event(paid("in_part_03", 3000, "evt_part_03")) == "applied"
    assert await apply_wedding_invoice_event(paid("in_part_03", 3000, "evt_part_03")) == "ignored"
    async with session_scope() as db:
        quote = await db.get(WeddingQuote, quote_id)
        assert quote.status == "paid" and quote.order_id is not None
        orders = (await db.scalars(select(Order))).all()
        assert len(orders) == 1
        assert len((await db.scalars(select(WeddingInvoice).where(WeddingInvoice.quote_id == quote_id))).all()) == 3


def test_dated_schedule_validation_and_eastern_due_time():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today = eastern_today()
    fields = dict(initial_send_mode="automatic", initial_send_date=today.isoformat(),
                  initial_due_date=(today + timedelta(days=7)).isoformat(),
                  balance_send_mode="automatic", balance_send_date=(today + timedelta(days=10)).isoformat(),
                  balance_due_date=(today + timedelta(days=20)).isoformat())
    saved = validate_schedule(fields, "deposit", today=today)
    assert saved["initial_due_date"] == today + timedelta(days=7)
    instant = datetime.fromtimestamp(due_timestamp(today), ZoneInfo("America/New_York"))
    assert (instant.hour, instant.minute, instant.second) == (23, 59, 59)
    for invalid in ({**fields, "balance_due_date": today.isoformat()},
                    {**fields, "initial_send_date": ""},
                    {**fields, "balance_send_date": ""}):
        with pytest.raises(ValueError):
            validate_schedule(invalid, "deposit", today=today)
    stale = {**fields, "initial_send_mode": "manual", "initial_send_date": "not-a-date",
             "balance_send_mode": "automatic", "balance_send_date": "not-a-date",
             "balance_due_date": "not-a-date"}
    saved = validate_schedule(stale, "full", today=today)
    assert saved["initial_send_date"] is None and saved["balance_send_date"] is None
    assert saved["balance_due_date"] is None and saved["balance_send_mode"] == "manual"


@pytest.mark.asyncio
async def test_approved_automatic_invoices_wait_for_dates_and_paid_deposit(monkeypatch):
    from app import weddings
    today = eastern_today()
    schedule = validate_schedule(dict(
        initial_send_mode="automatic", initial_send_date=today.isoformat(),
        initial_due_date=(today + timedelta(days=7)).isoformat(),
        balance_send_mode="automatic", balance_send_date=(today + timedelta(days=10)).isoformat(),
        balance_due_date=(today + timedelta(days=20)).isoformat()), "deposit")
    mock_stripe(monkeypatch, {"in_deposit": 3000, "in_balance": 3000})
    creates = []
    def create_invoice(**kwargs):
        creates.append(kwargs)
        return SimpleNamespace(id=f"in_{kwargs['metadata']['step']}")
    monkeypatch.setattr(stripe.Invoice, "create", create_invoice)
    snapshot, mode, deposit = validate_quote(form())
    async with session_scope() as db:
        inquiry = Inquiry(kind="wedding", name="Ava", email="ava@example.com")
        db.add(inquiry)
        await db.flush()
        quote = WeddingQuote(inquiry_id=inquiry.id, draft=snapshot, snapshot={},
                             payment_mode=mode, deposit_cents=deposit, activity=[], **schedule)
        db.add(quote)
        await db.commit()
        quote_id = quote.id
    await approve_wedding_schedule(quote_id)
    with pytest.raises(ValueError):
        await send_wedding_invoice(quote_id, "deposit")  # manual button cannot bypass scheduled approval
    assert len(await run_wedding_schedule()) == 1
    assert await run_wedding_schedule(apply=True) == [f"Wedding quote #{quote_id}: sent deposit invoice in_deposit"]
    assert creates[0]["due_date"] == due_timestamp(today + timedelta(days=7))
    assert "days_until_due" not in creates[0]
    assert await run_wedding_schedule(apply=True) == []  # no balance until the deposit is paid
    assert await apply_wedding_invoice_event(paid("in_deposit", 3000, "evt_deposit")) == "applied"
    assert await run_wedding_schedule(apply=True) == []  # not the balance date yet
    monkeypatch.setattr(weddings, "eastern_today", lambda: today + timedelta(days=10))
    assert await run_wedding_schedule(apply=True, today=today + timedelta(days=10)) == [
        f"Wedding quote #{quote_id}: sent balance invoice in_balance"]
    assert creates[1]["due_date"] == due_timestamp(today + timedelta(days=20))
    assert await run_wedding_schedule(apply=True, today=today + timedelta(days=10)) == []


@pytest.mark.asyncio
async def test_admin_can_approve_a_dated_quote_without_sending_yet():
    today = eastern_today()
    async with session_scope() as db:
        db.add(User(email="owner@example.com", password_hash=hash_password("password"), is_admin=True))
        inquiry = Inquiry(kind="wedding", name="Ava", email="ava@example.com")
        db.add(inquiry)
        await db.flush()
        db.add(WeddingQuote(inquiry_id=inquiry.id, draft={}, snapshot={}, activity=[]))
        await db.commit()
    await app.asgi_client.get("/admin/login")
    csrf = app.asgi_client.cookies.get(CSRF_COOKIE)
    await app.asgi_client.post("/admin/login", data=dict(email="owner@example.com", password="password", csrf_token=csrf))
    _, page = await app.asgi_client.get("/admin/weddings/1")
    assert page.status == 200 and "Send automatically on date" in page.text
    csrf = app.asgi_client.cookies.get(CSRF_COOKIE)
    _, saved = await app.asgi_client.post("/admin/weddings/1/save", data={
        **form(mode="full"), "csrf_token": csrf, "initial_send_mode": "automatic",
        "initial_send_date": (today + timedelta(days=2)).isoformat(),
        "initial_due_date": (today + timedelta(days=9)).isoformat(),
    })
    assert saved.status == 302
    _, page = await app.asgi_client.get("/admin/weddings/1")
    assert "Approve and schedule first invoice" in page.text
    csrf = app.asgi_client.cookies.get(CSRF_COOKIE)
    _, scheduled = await app.asgi_client.post("/admin/weddings/1/schedule", data={"csrf_token": csrf})
    assert scheduled.status == 302
    async with session_scope() as db:
        quote = await db.get(WeddingQuote, 1)
        assert quote.status == "scheduled" and quote.snapshot["total_cents"] == 6000
        assert (await db.scalars(select(WeddingInvoice))).all() == []


@pytest.mark.asyncio
async def test_admin_hides_irrelevant_payment_fields_and_builds_installments():
    today = eastern_today()
    async with session_scope() as db:
        db.add(User(email="owner@example.com", password_hash=hash_password("password"), is_admin=True))
        inquiry = Inquiry(kind="wedding", name="Ava", email="ava@example.com")
        db.add(inquiry)
        await db.flush()
        db.add(WeddingQuote(inquiry_id=inquiry.id, draft={}, snapshot={}, activity=[]))
        await db.commit()
    await app.asgi_client.get("/admin/login")
    csrf = app.asgi_client.cookies.get(CSRF_COOKIE)
    await app.asgi_client.post("/admin/login", data=dict(email="owner@example.com", password="password", csrf_token=csrf))
    _, page = await app.asgi_client.get("/admin/weddings/1")
    assert page.status == 200
    assert 'data-payment-modes="deposit" hidden' in page.text
    assert 'id="add-quote-line"' in page.text
    assert page.text.count('data-line-id="1"') == 1
    assert page.text.index('id="quote-lines"') < page.text.index('id="wpayment"')
    csrf = app.asgi_client.cookies.get(CSRF_COOKIE)
    fields = form(mode="full") | {"deposit": "200.00", "csrf_token": csrf}
    _, saved = await app.asgi_client.post("/admin/weddings/1/save", data=fields)
    assert saved.status == 302
    async with session_scope() as db:
        assert (await db.get(WeddingQuote, 1)).deposit_cents == 0
    fields = installment_form(today) | {"deposit": "200.00"}
    fields["line_ids"] = "1,2,3,4,5,6,7"
    for index in range(3, 8):
        fields[f"name_{index}"] = f"Extra service {index}"
        fields[f"quantity_{index}"] = "1"
        fields[f"price_{index}"] = "1.00"
    # Update the final installment so the plan still sums to all seven quote lines ($65).
    fields["installment_amount_3"] = "35.00"
    await app.asgi_client.get("/admin/weddings/1")
    csrf = app.asgi_client.cookies.get(CSRF_COOKIE)
    _, saved = await app.asgi_client.post("/admin/weddings/1/save", data={**fields, "csrf_token": csrf})
    assert saved.status == 302
    _, page = await app.asgi_client.get("/admin/weddings/1")
    assert page.text.count('data-line-id="7"') == 1
    assert 'data-payment-modes="full deposit" hidden' in page.text
    assert "$65.00" in page.text and "Payment plan" in page.text
    csrf = app.asgi_client.cookies.get(CSRF_COOKIE)
    fields["installment_ids"] = "1,2,3,4,5,6,7"
    for index, percent in enumerate((20, 20, 20, 10, 10, 10, 10), start=1):
        fields[f"installment_type_{index}"] = "percent"
        fields[f"installment_percent_{index}"] = str(percent)
        fields[f"installment_due_date_{index}"] = (today + timedelta(days=index * 7)).isoformat()
    _, saved = await app.asgi_client.post("/admin/weddings/1/save", data={**fields, "csrf_token": csrf})
    assert saved.status == 302
    _, page = await app.asgi_client.get("/admin/weddings/1")
    assert page.text.count('data-installment-id="7"') == 1
    assert 'id="add-installment"' in page.text and 'id="installment-total"' in page.text
    assert 'value="10"' in page.text and "(20% of quote total" in page.text
    async with session_scope() as db:
        quote = await db.get(WeddingQuote, 1)
        assert len(quote.installments) == 7
        assert sum(part["amount_cents"] for part in quote.installments) == quote.draft["total_cents"]


@pytest.mark.asyncio
async def test_deposit_books_work_balance_creates_one_paid_order(monkeypatch):
    mock_stripe(monkeypatch, {"in_deposit": 3000, "in_balance": 3000})
    snapshot, mode, deposit = validate_quote(form())
    async with session_scope() as db:
        inquiry = Inquiry(kind="wedding", name="Ava", email="ava@example.com")
        db.add(inquiry)
        await db.flush()
        quote = WeddingQuote(inquiry_id=inquiry.id, draft=snapshot, snapshot={}, payment_mode=mode, deposit_cents=deposit, activity=[])
        db.add(quote)
        await db.commit()
        quote_id = quote.id
    assert await send_wedding_invoice(quote_id, "deposit") == "in_deposit"
    with pytest.raises(ValueError):
        await send_wedding_invoice(quote_id, "deposit")
    assert await apply_wedding_invoice_event(paid("in_deposit", 1, "evt_wrong")) == "review"
    assert await apply_wedding_invoice_event(paid("in_deposit", 3000, "evt_deposit")) == "applied"
    assert await apply_wedding_invoice_event(paid("in_deposit", 3000, "evt_deposit")) == "ignored"
    async with session_scope() as db:
        assert (await db.get(WeddingQuote, quote_id)).status == "deposit_paid"
        assert (await db.scalars(select(Order))).all() == []
    assert await send_wedding_invoice(quote_id, "balance") == "in_balance"
    assert await apply_wedding_invoice_event(paid("in_balance", 3000, "evt_balance")) == "applied"
    async with session_scope() as db:
        quote = await db.get(WeddingQuote, quote_id)
        assert quote.status == "paid" and quote.order_id is not None
        order = await db.get(Order, quote.order_id)
        assert order.status == "paid" and order.payment_method == "stripe_invoice"
        lines = (await db.scalars(select(OrderItem).where(OrderItem.order_id == order.id))).all()
        assert len(lines) == 2 and all(line.listing_id is None for line in lines)
        assert len((await db.scalars(select(WeddingInvoice))).all()) == 2


@pytest.mark.asyncio
async def test_full_upfront_and_wedding_admin_gating(monkeypatch):
    mock_stripe(monkeypatch, {"in_full": 6000})
    async with session_scope() as db:
        db.add(User(email="owner@example.com", password_hash=hash_password("password"), is_admin=True))
        inquiry = Inquiry(kind="wedding", name="Ava", email="ava@example.com")
        db.add(inquiry)
        await db.commit()
        inquiry_id = inquiry.id
    _, anonymous = await app.asgi_client.get(f"/admin/weddings/from-inquiry/{inquiry_id}")
    assert anonymous.status == 302
    await app.asgi_client.get("/admin/login")
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    await app.asgi_client.post("/admin/login", data=dict(email="owner@example.com", password="password", csrf_token=token))
    token = await app.asgi_client.get(f"/admin/weddings/from-inquiry/{inquiry_id}")
    csrf = app.asgi_client.cookies.get(CSRF_COOKIE)
    _, start = await app.asgi_client.post(f"/admin/weddings/from-inquiry/{inquiry_id}", data={"csrf_token": csrf})
    assert start.status == 302
    _, preview = await app.asgi_client.get("/admin/weddings/1")
    assert preview.status == 200
    csrf = app.asgi_client.cookies.get(CSRF_COOKIE)
    _, saved = await app.asgi_client.post("/admin/weddings/1/save", data={**form(mode="full"), "csrf_token": csrf})
    assert saved.status == 302
    _, preview = await app.asgi_client.get("/admin/weddings/1")
    assert "$60.00" in preview.text
    assert await send_wedding_invoice(1, "full") == "in_full"
    assert await apply_wedding_invoice_event(paid("in_full", 6000, "evt_full")) == "applied"
    async with session_scope() as db:
        assert (await db.get(WeddingQuote, 1)).status == "paid"


@pytest.mark.asyncio
async def test_out_of_order_and_voided_deposit_never_book():
    snapshot, _, deposit = validate_quote(form())
    async with session_scope() as db:
        inquiry = Inquiry(kind="wedding", name="Ava", email="ava@example.com")
        db.add(inquiry)
        await db.flush()
        quote = WeddingQuote(inquiry_id=inquiry.id, status="sent", draft=snapshot,
                             snapshot=snapshot, payment_mode="deposit", deposit_cents=deposit, activity=[])
        db.add(quote)
        await db.flush()
        db.add(WeddingInvoice(quote_id=quote.id, step="deposit", status="sent", amount_cents=deposit,
                              stripe_invoice_id="in_deposit"))
        await db.commit()
        quote_id = quote.id
    assert await apply_wedding_invoice_event(paid("in_deposit", 3000, "evt_bad_oob") | {
        "data": {"object": {**paid("in_deposit", 3000, "evt_bad_oob")["data"]["object"], "paid_out_of_band": True}}
    }) == "review"
    assert await apply_wedding_invoice_event(dict(id="evt_void", type="invoice.voided",
        data={"object": {"id": "in_deposit"}})) == "applied"
    assert await apply_wedding_invoice_event(dict(id="evt_void_again", type="invoice.voided",
        data={"object": {"id": "in_deposit"}})) == "ignored"
    assert await apply_wedding_invoice_event(paid("in_deposit", 3000, "evt_late")) == "review"
    async with session_scope() as db:
        assert (await db.get(WeddingQuote, quote_id)).status == "void"
        assert not (await db.scalars(select(Order))).all()


@pytest.mark.asyncio
async def test_signed_webhook_routes_wedding_invoice_not_bouquet(monkeypatch):
    from app import weddings
    from app import proposals
    settings = get_settings()
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_mock")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_mock")
    async with session_scope() as db:
        inquiry = Inquiry(kind="wedding", name="Ava", email="ava@example.com")
        db.add(inquiry)
        await db.flush()
        quote = WeddingQuote(inquiry_id=inquiry.id, status="sent", draft={}, snapshot={}, activity=[])
        db.add(quote)
        await db.flush()
        db.add(WeddingInvoice(quote_id=quote.id, step="full", status="sent", amount_cents=1000,
                              stripe_invoice_id="in_wedding_route"))
        await db.commit()
    event = dict(id="evt_route", type="invoice.paid", data={"object": {"id": "in_wedding_route"}})
    monkeypatch.setattr(stripe.Webhook, "construct_event", lambda *args: event)
    outcomes = []
    async def wedding_handler(value):
        outcomes.append("wedding")
        return "ignored"
    async def bouquet_handler(value):
        outcomes.append("bouquet")
        return "ignored"
    monkeypatch.setattr(weddings, "apply_wedding_invoice_event", wedding_handler)
    monkeypatch.setattr(proposals, "apply_invoice_event", bouquet_handler)
    _, response = await app.asgi_client.post("/api/stripe/webhook/", data=b"signed")
    assert response.status == 200 and outcomes == ["wedding"]
