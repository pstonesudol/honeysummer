from decimal import Decimal
from uuid import uuid4

import pytest
import stripe
from sqlalchemy import select

from app.admin import CSRF_COOKIE
from app.auth import hash_password
from app.balance_report import invoice_balance_rows
from app.db import session_scope
from app.invoice_refund_audit import audit
from app.invoice_refunds import (
    close_fully_refunded_quote,
    import_external_invoice_refund,
    issue_invoice_refund,
    reconcile_invoice_refund,
)
from app.models import (
    BouquetProposal,
    Inquiry,
    InvoiceRefund,
    Order,
    OrderItem,
    OrderRefund,
    User,
    WeddingInvoice,
    WeddingQuote,
)
from app.proposals import apply_invoice_event
from app.server import app
from app.settings import get_settings
from app.weddings import send_wedding_invoice


def stripe_payment(monkeypatch, *, total=1000, invoice_id="in_one", refunded=0):
    settings = get_settings()
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_mock")

    class Data(dict):
        def __getattr__(self, name):
            return self[name]

    monkeypatch.setattr(
        stripe.Invoice, "retrieve", lambda _: Data(id=invoice_id, status="paid", currency="usd", total=total)
    )
    monkeypatch.setattr(
        stripe.InvoicePayment,
        "list",
        lambda **kwargs: Data(
            has_more=False,
            data=[
                Data(
                    invoice=invoice_id,
                    status="paid",
                    currency="usd",
                    amount_paid=total,
                    payment=Data(type="payment_intent", payment_intent="pi_one"),
                )
            ],
        ),
    )
    monkeypatch.setattr(
        stripe.PaymentIntent,
        "retrieve",
        lambda _: Data(id="pi_one", status="succeeded", currency="usd", amount_received=total, latest_charge="ch_one"),
    )
    refunded_amount = [refunded]
    monkeypatch.setattr(
        stripe.Charge,
        "retrieve",
        lambda _: Data(id="ch_one", payment_intent="pi_one", amount_refunded=refunded_amount[0]),
    )
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        refunded_amount[0] += kwargs["amount"]
        return Data(
            id=f"re_{len(calls)}", status="succeeded", amount=kwargs["amount"], currency="usd", payment_intent="pi_one"
        )

    monkeypatch.setattr(stripe.Refund, "create", create)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("external", [False, True])
async def test_stock_shortfall_can_be_refunded_without_booking_or_restocking(monkeypatch, external):
    calls = stripe_payment(monkeypatch, refunded=1000 if external else 0)
    async with session_scope() as db:
        db.add(User(email="owner@example.com", password_hash="unused", is_admin=True))
        inquiry = Inquiry(kind="bouquet", name="Buyer", email="buyer@example.com")
        db.add(inquiry)
        await db.flush()
        db.add(
            BouquetProposal(
                inquiry_id=inquiry.id,
                status="stock_review",
                stripe_invoice_id="in_one",
                history=[{"draft": {"total_cents": 1000}}],
                activity=[],
            )
        )
        await db.commit()
    if external:
        monkeypatch.setattr(
            stripe.Refund,
            "retrieve",
            lambda _: stripe.StripeObject.construct_from(
                dict(
                    id="re_external",
                    status="succeeded",
                    amount=1000,
                    currency="usd",
                    payment_intent="pi_one",
                    charge="ch_one",
                    metadata={},
                ),
                "sk_test_mock",
            ),
        )
        await import_external_invoice_refund("bouquet", 1, "re_external", 1)
        await import_external_invoice_refund("bouquet", 1, "re_external", 1)
        assert calls == []
    else:
        form = dict(refund_key=str(uuid4()), amount="10.00", reason="Unavailable flowers")
        await issue_invoice_refund("bouquet", 1, form, 1)
        await issue_invoice_refund("bouquet", 1, form, 1)
        assert len(calls) == 1
    event = dict(
        type="invoice.paid",
        data={
            "object": dict(
                id="in_one",
                status="paid",
                currency="usd",
                total=1000,
                amount_paid=1000,
                amount_remaining=0,
            )
        },
    )
    assert await apply_invoice_event(event) == "review"
    await close_fully_refunded_quote("bouquet", 1, 1)
    async with session_scope() as db:
        proposal = await db.get(BouquetProposal, 1)
        assert proposal.status == "cancelled" and proposal.order_id is None
        assert len((await db.scalars(select(InvoiceRefund))).all()) == 1
        assert not (await db.scalars(select(Order))).all()
        assert not (await db.scalars(select(OrderRefund))).all()


@pytest.mark.asyncio
async def test_external_invoice_refund_import_is_verified_idempotent_and_never_issues_refund(monkeypatch):
    calls = stripe_payment(monkeypatch, refunded=400)

    class Remote(dict):
        def __getattr__(self, key):
            return self[key]

    remote = Remote(
        id="re_external",
        status="succeeded",
        amount=400,
        currency="usd",
        payment_intent="pi_one",
        charge="ch_one",
        metadata={},
    )
    monkeypatch.setattr(stripe.Refund, "retrieve", lambda _: remote)
    async with session_scope() as db:
        owner = User(email="owner@example.com", password_hash="unused", is_admin=True)
        inquiry = Inquiry(kind="wedding", name="Ava", email="ava@example.com")
        db.add_all([owner, inquiry])
        await db.flush()
        quote = WeddingQuote(
            inquiry_id=inquiry.id,
            status="deposit_paid",
            payment_mode="deposit",
            snapshot={"total_cents": 2500},
            activity=[],
        )
        db.add(quote)
        await db.flush()
        invoice = WeddingInvoice(
            quote_id=quote.id, step="deposit", status="paid", amount_cents=1000, stripe_invoice_id="in_one"
        )
        db.add(invoice)
        await db.commit()
        pk, quote_id = invoice.id, quote.id
    remote["payment_intent"] = "pi_wrong"
    with pytest.raises(ValueError, match="original payment"):
        await import_external_invoice_refund("wedding", pk, "re_external", 1)
    remote["payment_intent"] = "pi_one"
    findings = await audit()
    assert len(findings) == 1 and "Stripe refunded 400 cents; local journal 0 cents" in findings[0]
    await import_external_invoice_refund("wedding", pk, "re_external", 1)
    await import_external_invoice_refund("wedding", pk, "re_external", 1)
    assert calls == []
    assert await audit() == []
    async with session_scope() as db:
        rows = (await db.scalars(select(InvoiceRefund))).all()
        assert len(rows) == 1 and rows[0].amount_cents == 400 and rows[0].status == "succeeded"
        assert (await db.get(WeddingQuote, quote_id)).status == "review"
        quote = await db.get(WeddingQuote, quote_id)
        quote.status = "deposit_paid"  # Even an accidental recovery cannot authorize old-plan sends.
        await db.commit()
    monkeypatch.setattr(get_settings(), "stripe_webhook_secret", "whsec_mock")
    with pytest.raises(ValueError, match="paused the original payment plan"):
        await send_wedding_invoice(quote_id, "balance")


@pytest.mark.asyncio
async def test_wedding_deposit_refund_pauses_next_invoice_without_creating_order(monkeypatch):
    calls = stripe_payment(monkeypatch)
    async with session_scope() as db:
        db.add(User(email="owner@example.com", password_hash="unused", is_admin=True))
        inquiry = Inquiry(kind="wedding", name="Ava", email="ava@example.com")
        db.add(inquiry)
        await db.flush()
        quote = WeddingQuote(
            inquiry_id=inquiry.id,
            status="deposit_paid",
            payment_mode="deposit",
            deposit_cents=1000,
            draft={"total_cents": 2500},
            snapshot={"total_cents": 2500},
            activity=[],
        )
        db.add(quote)
        await db.flush()
        invoice = WeddingInvoice(
            quote_id=quote.id, step="deposit", status="paid", stripe_invoice_id="in_one", amount_cents=1000
        )
        db.add(invoice)
        await db.commit()
        invoice_id, quote_id = invoice.id, quote.id
    form = dict(refund_key=str(uuid4()), amount="4.00", reason="Customer request")
    result = await issue_invoice_refund("wedding", invoice_id, form, 1)
    assert result.status == "succeeded" and calls[0]["payment_intent"] == "pi_one"
    assert (await issue_invoice_refund("wedding", invoice_id, form, 1)).id == result.id
    with pytest.raises(ValueError, match="remaining paid"):
        await issue_invoice_refund("wedding", invoice_id, {**form, "refund_key": str(uuid4()), "amount": "6.01"}, 1)
    async with session_scope() as db:
        quote = await db.get(WeddingQuote, quote_id)
        assert quote.status == "review" and quote.order_id is None
        assert (await db.scalars(select(Order))).all() == []
        assert len((await db.scalars(select(InvoiceRefund))).all()) == 1

        balances = await invoice_balance_rows(db)
        assert balances[0]["refunded_cents"] == 400
        assert balances[0]["verified_paid_cents"] == 1000
        assert balances[0]["balance_cents"] == 1500  # Agreed terms not rewritten by a refund.
    assert len(calls) == 1
    with pytest.raises(ValueError, match="Every paid invoice"):
        await close_fully_refunded_quote("wedding", quote_id, 1)
    await issue_invoice_refund(
        "wedding", invoice_id, dict(refund_key=str(uuid4()), amount="6.00", reason="Customer request"), 1
    )
    await close_fully_refunded_quote("wedding", quote_id, 1)
    async with session_scope() as db:
        assert (await db.get(WeddingQuote, quote_id)).status == "cancelled"


@pytest.mark.asyncio
async def test_paid_bouquet_refunds_record_order_net_and_keep_inventory_separate(monkeypatch):
    stripe_payment(monkeypatch)
    async with session_scope() as db:
        db.add(User(email="owner@example.com", password_hash="unused", is_admin=True))
        inquiry = Inquiry(kind="bouquet", name="Ava", email="ava@example.com")
        db.add(inquiry)
        order = Order(
            status="paid",
            payment_method="stripe_invoice",
            items=[OrderItem(name_snapshot="Bouquet", price_snapshot=Decimal("10.00"), quantity=1)],
        )
        db.add(order)
        await db.flush()
        proposal = BouquetProposal(
            inquiry_id=inquiry.id,
            order_id=order.id,
            status="paid",
            stripe_invoice_id="in_one",
            history=[{"draft": {"total_cents": 1000}}],
            activity=[],
        )
        db.add(proposal)
        await db.commit()
        proposal_id, order_id = proposal.id, order.id
    first = dict(refund_key=str(uuid4()), amount="4.00", reason="Damaged")
    assert (await issue_invoice_refund("bouquet", proposal_id, first, 1)).status == "succeeded"
    assert (
        await issue_invoice_refund("bouquet", proposal_id, {**first, "refund_key": str(uuid4()), "amount": "6.00"}, 1)
    ).status == "succeeded"
    async with session_scope() as db:
        order = await db.get(Order, order_id)
        assert order.status == "refunded"
        entries = (await db.scalars(select(OrderRefund).where(OrderRefund.order_id == order_id))).all()
        assert sum(entry.amount_cents for entry in entries) == 1000


@pytest.mark.asyncio
async def test_paid_amended_wedding_refunds_use_revised_order_total(monkeypatch):
    stripe_payment(monkeypatch, total=4000, invoice_id="in_amended")
    async with session_scope() as db:
        owner = User(email="owner@example.com", password_hash="unused", is_admin=True)
        inquiry = Inquiry(kind="wedding", name="Ava", email="ava@example.com")
        order = Order(
            status="paid",
            payment_method="stripe_invoice",
            items=[OrderItem(name_snapshot="Revised wedding", price_snapshot=Decimal("60.00"), quantity=1)],
        )
        db.add_all([owner, inquiry, order])
        await db.flush()
        quote = WeddingQuote(
            inquiry_id=inquiry.id,
            order_id=order.id,
            status="paid",
            payment_mode="deposit",
            snapshot={"total_cents": 3000},
            amendments=[{"draft": {"total_cents": 6000}, "amount_cents": 4000, "retained_paid_cents": 2000}],
            activity=[],
        )
        db.add(quote)
        await db.flush()
        invoice = WeddingInvoice(
            quote_id=quote.id, step="amended", status="paid", stripe_invoice_id="in_amended", amount_cents=4000
        )
        db.add(invoice)
        await db.commit()
        invoice_id, order_id = invoice.id, order.id
    row = await issue_invoice_refund(
        "wedding", invoice_id, dict(refund_key=str(uuid4()), amount="40.00", reason="Customer request"), 1
    )
    assert row.status == "succeeded"
    async with session_scope() as db:
        order = await db.get(Order, order_id)
        assert order.status == "paid"
        assert (await db.scalar(select(OrderRefund.amount_cents).where(OrderRefund.order_id == order_id))) == 4000


@pytest.mark.asyncio
async def test_uncertain_invoice_refund_blocks_all_other_attempts(monkeypatch):
    stripe_payment(monkeypatch)

    def fail(**kwargs):
        raise RuntimeError("connection lost")

    monkeypatch.setattr(stripe.Refund, "create", fail)
    async with session_scope() as db:
        db.add(User(email="owner@example.com", password_hash="unused", is_admin=True))
        inquiry = Inquiry(kind="wedding", name="Ava", email="ava@example.com")
        db.add(inquiry)
        await db.flush()
        quote = WeddingQuote(
            inquiry_id=inquiry.id,
            status="deposit_paid",
            payment_mode="deposit",
            deposit_cents=1000,
            snapshot={"total_cents": 2500},
            activity=[],
        )
        db.add(quote)
        await db.flush()
        invoice = WeddingInvoice(
            quote_id=quote.id, step="deposit", status="paid", stripe_invoice_id="in_one", amount_cents=1000
        )
        db.add(invoice)
        await db.commit()
        invoice_id = invoice.id
    form = dict(refund_key=str(uuid4()), amount="4.00", reason="Customer request")
    with pytest.raises(ValueError, match="uncertain"):
        await issue_invoice_refund("wedding", invoice_id, form, 1)
    assert (await issue_invoice_refund("wedding", invoice_id, form, 1)).status == "review"
    with pytest.raises(ValueError, match="earlier refund"):
        await issue_invoice_refund("wedding", invoice_id, {**form, "refund_key": str(uuid4())}, 1)


@pytest.mark.asyncio
async def test_admin_invoice_refund_requires_login_csrf_and_shows_history(monkeypatch):
    stripe_payment(monkeypatch)
    async with session_scope() as db:
        db.add(User(email="owner@example.com", password_hash=hash_password("password"), is_admin=True))
        inquiry = Inquiry(kind="wedding", name="Ava", email="ava@example.com")
        db.add(inquiry)
        await db.flush()
        quote = WeddingQuote(
            inquiry_id=inquiry.id,
            status="deposit_paid",
            payment_mode="deposit",
            deposit_cents=1000,
            draft={"total_cents": 2500},
            snapshot={"total_cents": 2500},
            activity=[],
        )
        db.add(quote)
        await db.flush()
        invoice = WeddingInvoice(
            quote_id=quote.id, step="deposit", status="paid", stripe_invoice_id="in_one", amount_cents=1000
        )
        db.add(invoice)
        await db.commit()
        invoice_id, quote_id = invoice.id, quote.id
    url = f"/admin/invoice-refunds/wedding/{invoice_id}"
    _, anonymous = await app.asgi_client.post(url, data={})
    assert anonymous.status == 302
    await app.asgi_client.get("/admin/login")
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    await app.asgi_client.post(
        "/admin/login", data=dict(email="owner@example.com", password="password", csrf_token=token)
    )
    _, invalid = await app.asgi_client.post(url, data={})
    assert invalid.status == 403
    _, detail = await app.asgi_client.get(f"/admin/weddings/{quote_id}")
    assert detail.status == 200 and "Initiate invoice payment refund" in detail.text
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    _, issued = await app.asgi_client.post(
        url, data=dict(csrf_token=token, refund_key=str(uuid4()), amount="4.00", reason="Change of plans")
    )
    assert issued.status == 302
    _, detail = await app.asgi_client.get(f"/admin/weddings/{quote_id}")
    assert "Change of plans" in detail.text and "re_1" in detail.text
    _, attention = await app.asgi_client.get("/admin/operations/attention")
    assert attention.status == 200


@pytest.mark.asyncio
async def test_refund_with_known_pending_id_can_be_verified_once(monkeypatch):
    stripe_payment(monkeypatch)

    class Remote(dict):
        def __getattr__(self, key):
            return self[key]

    monkeypatch.setattr(
        stripe.Refund,
        "create",
        lambda **kwargs: Remote(
            id="re_pending", status="pending", amount=kwargs["amount"], currency="usd", payment_intent="pi_one"
        ),
    )
    async with session_scope() as db:
        db.add(User(email="owner@example.com", password_hash="unused", is_admin=True))
        inquiry = Inquiry(kind="bouquet", name="Ava", email="ava@example.com")
        db.add(inquiry)
        order = Order(
            status="paid",
            payment_method="stripe_invoice",
            items=[OrderItem(name_snapshot="Bouquet", price_snapshot=Decimal("10.00"), quantity=1)],
        )
        db.add(order)
        await db.flush()
        proposal = BouquetProposal(
            inquiry_id=inquiry.id,
            order_id=order.id,
            status="paid",
            stripe_invoice_id="in_one",
            history=[{"draft": {"total_cents": 1000}}],
            activity=[],
        )
        db.add(proposal)
        await db.commit()
        proposal_id, order_id = proposal.id, order.id
    row = await issue_invoice_refund(
        "bouquet", proposal_id, dict(refund_key=str(uuid4()), amount="10.00", reason="Customer request"), 1
    )
    assert row.status == "review" and row.stripe_refund_id == "re_pending"

    def retrieve(_):
        return Remote(
            id="re_pending",
            status="succeeded",
            currency="usd",
            amount=1000,
            payment_intent="pi_one",
            metadata={"invoice_refund_id": str(row.id)},
        )

    monkeypatch.setattr(stripe.Refund, "retrieve", retrieve)
    assert await reconcile_invoice_refund(row.id) == "succeeded"
    assert await reconcile_invoice_refund(row.id) == "succeeded"
    async with session_scope() as db:
        assert (await db.get(Order, order_id)).status == "refunded"
        assert len((await db.scalars(select(OrderRefund))).all()) == 1


@pytest.mark.asyncio
async def test_unrecorded_stripe_refund_blocks_new_invoice_refund(monkeypatch):
    stripe_payment(monkeypatch, refunded=200)
    async with session_scope() as db:
        db.add(User(email="owner@example.com", password_hash="unused", is_admin=True))
        inquiry = Inquiry(kind="wedding", name="Ava", email="ava@example.com")
        db.add(inquiry)
        await db.flush()
        quote = WeddingQuote(
            inquiry_id=inquiry.id,
            status="deposit_paid",
            payment_mode="deposit",
            deposit_cents=1000,
            snapshot={"total_cents": 2500},
            activity=[],
        )
        db.add(quote)
        await db.flush()
        invoice = WeddingInvoice(
            quote_id=quote.id, step="deposit", status="paid", stripe_invoice_id="in_one", amount_cents=1000
        )
        db.add(invoice)
        await db.commit()
        invoice_id = invoice.id
    with pytest.raises(ValueError, match="refunds not recorded"):
        await issue_invoice_refund(
            "wedding", invoice_id, dict(refund_key=str(uuid4()), amount="4.00", reason="Customer request"), 1
        )
    async with session_scope() as db:
        assert (await db.scalars(select(InvoiceRefund))).all() == []


@pytest.mark.asyncio
async def test_refund_of_final_paid_wedding_invoice_reduces_order_net_not_stock(monkeypatch):
    stripe_payment(monkeypatch)
    async with session_scope() as db:
        db.add(User(email="owner@example.com", password_hash="unused", is_admin=True))
        inquiry = Inquiry(kind="wedding", name="Ava", email="ava@example.com")
        db.add(inquiry)
        order = Order(
            status="paid",
            payment_method="stripe_invoice",
            items=[OrderItem(name_snapshot="Flowers", price_snapshot=Decimal("10.00"), quantity=1)],
        )
        db.add(order)
        await db.flush()
        quote = WeddingQuote(
            inquiry_id=inquiry.id,
            order_id=order.id,
            status="paid",
            payment_mode="full",
            snapshot={"total_cents": 1000},
            activity=[],
        )
        db.add(quote)
        await db.flush()
        invoice = WeddingInvoice(
            quote_id=quote.id, step="full", status="paid", stripe_invoice_id="in_one", amount_cents=1000
        )
        db.add(invoice)
        await db.commit()
        invoice_id, order_id = invoice.id, order.id
    await issue_invoice_refund(
        "wedding", invoice_id, dict(refund_key=str(uuid4()), amount="10.00", reason="Cancelled event"), 1
    )
    async with session_scope() as db:
        assert (await db.get(Order, order_id)).status == "refunded"
        assert len((await db.scalars(select(OrderRefund))).all()) == 1
