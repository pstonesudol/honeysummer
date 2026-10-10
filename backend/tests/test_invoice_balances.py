from datetime import UTC, datetime, timedelta

import pytest

from app.admin import CSRF_COOKIE
from app.auth import hash_password
from app.balance_report import invoice_balance_rows
from app.db import session_scope
from app.models import BouquetProposal, Inquiry, User, WeddingInvoice, WeddingQuote
from app.server import app
from app.weddings import eastern_today


@pytest.mark.asyncio
async def test_balances_separate_partial_payments_open_invoices_and_uncertain_sends():
    today = eastern_today()
    async with session_scope() as db:
        db.add(User(email="owner@example.com", password_hash=hash_password("password"), is_admin=True))
        people = [
            Inquiry(kind=kind, name=name, email=f"buyer{index}@example.com")
            for index, (kind, name) in enumerate(
                (
                    ("wedding", "Wedding A"),
                    ("wedding", "Wedding B"),
                    ("wedding", "Uncertain"),
                    ("bouquet", "=Formula customer"),
                    ("bouquet", "Paid in Stripe"),
                ),
                start=1,
            )
        ]
        db.add_all(people)
        await db.flush()
        snapshot = dict(title="Flowers", total_cents=10000)
        deposit = WeddingQuote(
            inquiry_id=people[0].id,
            status="balance_sent",
            payment_mode="deposit",
            snapshot=snapshot,
            draft=snapshot,
            deposit_cents=3000,
            balance_due_date=today - timedelta(days=1),
            activity=[],
        )
        installment = WeddingQuote(
            inquiry_id=people[1].id,
            status="installment_paid",
            payment_mode="installments",
            snapshot=snapshot,
            draft=snapshot,
            activity=[],
            installments=[
                dict(amount_cents=2000, due_date=today.isoformat()),
                dict(amount_cents=8000, due_date=(today + timedelta(days=7)).isoformat()),
            ],
        )
        uncertain = WeddingQuote(
            inquiry_id=people[2].id,
            status="review",
            payment_mode="deposit",
            snapshot=snapshot,
            draft=snapshot,
            activity=[],
        )
        now = datetime.now(UTC)
        proposal = BouquetProposal(
            inquiry_id=people[3].id,
            status="sent",
            stripe_invoice_id="in_bouquet",
            draft=snapshot,
            history=[dict(draft=snapshot, sent_at=now.isoformat())],
            activity=[],
        )
        paid_in_stripe = BouquetProposal(
            inquiry_id=people[4].id,
            status="stock_review",
            stripe_invoice_id="in_paid",
            draft=snapshot,
            history=[dict(draft=snapshot, sent_at=now.isoformat())],
            activity=[],
        )
        db.add_all([deposit, installment, uncertain, proposal, paid_in_stripe])
        await db.flush()
        db.add_all(
            [
                WeddingInvoice(quote_id=deposit.id, step="deposit", status="paid", amount_cents=3000),
                WeddingInvoice(quote_id=deposit.id, step="balance", status="sent", amount_cents=7000),
                WeddingInvoice(quote_id=installment.id, step="part_01", status="paid", amount_cents=2000),
                WeddingInvoice(quote_id=uncertain.id, step="deposit", status="review", amount_cents=3000),
            ]
        )
        await db.commit()
        async_rows = await invoice_balance_rows(db, today=today)
    assert len(async_rows) == 4
    by_customer = {row["customer"]: row for row in async_rows}
    assert by_customer["Wedding A"]["verified_paid_cents"] == 3000
    assert by_customer["Wedding A"]["balance_cents"] == 7000
    assert by_customer["Wedding A"]["open_cents"] == 7000
    assert by_customer["Wedding A"]["overdue"]
    assert by_customer["Wedding B"]["open_cents"] == 0
    assert by_customer["Wedding B"]["balance_cents"] == 8000
    assert by_customer["Uncertain"]["open_cents"] == 0
    assert by_customer["Uncertain"]["needs_review"]
    # A bouquet paid in Stripe but blocked on catalogue stock is not outstanding debt.
    assert "Paid in Stripe" not in by_customer
    _, anonymous = await app.asgi_client.get("/admin/reports/balances?format=csv")
    assert anonymous.status in (302, 303) and anonymous.headers["location"].endswith("/admin/login")
    await app.asgi_client.get("/admin/login")
    csrf = app.asgi_client.cookies.get(CSRF_COOKIE)
    await app.asgi_client.post(
        "/admin/login", data=dict(email="owner@example.com", password="password", csrf_token=csrf)
    )
    _, page = await app.asgi_client.get("/admin/reports/balances")
    assert page.status == 200
    assert "Invoice balances" in page.text and "Wedding A" in page.text
    assert "=Formula customer" in page.text and "Paid in Stripe" not in page.text
    assert "$100.00" in page.text
    assert "$170.00" in page.text
    assert "$50.00" in page.text  # Only signed wedding payments ($30 + $20).
    _, export = await app.asgi_client.get("/admin/reports/balances?format=csv")
    assert export.status == 200
    assert "'=Formula customer" in export.text
    assert "Paid in Stripe" not in export.text
