from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.admin import CSRF_COOKIE
from app.auth import hash_password
from app.db import session_scope
from app.models import FlowerListing, InventoryMovement, Order, OrderItem, OrderRefund, User
from app.refunds import issue_refund
from app.server import app


async def make_order(method="cash"):
    async with session_scope() as db:
        db.add(User(email="owner@example.com", password_hash=hash_password("password"), is_admin=True))
        listing = FlowerListing(name="Peony", price=Decimal("8.00"), quantity_available=5)
        db.add(listing)
        await db.flush()
        order = Order(status="paid", payment_method=method, delivery_fee=Decimal("2.00"),
                      stripe_payment_intent_id="pi_test" if method == "stripe_checkout" else None,
                      items=[OrderItem(listing_id=listing.id, name_snapshot="Peony",
                                       price_snapshot=Decimal("8.00"), quantity=1)])
        db.add(order)
        await db.commit()
        return order.id, listing.id


def test_refund_migration_creates_table_on_existing_schema():
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect

    path = Path(__file__).resolve().parents[1] / "migrations/versions/751e841829ae_order_refunds.py"
    spec = spec_from_file_location("refund_migration", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            module.upgrade()
        assert "order_refunds" in inspect(connection).get_table_names()
        with Operations.context(context):
            module.downgrade()
        assert "order_refunds" not in inspect(connection).get_table_names()


@pytest.mark.asyncio
async def test_manual_refund_is_idempotent_partial_then_full_without_stock_change():
    order_id, listing_id = await make_order()
    _, anonymous = await app.asgi_client.post(f"/admin/orders/{order_id}/refund", data={})
    assert anonymous.status == 302
    await app.asgi_client.get("/admin/login")
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    await app.asgi_client.post("/admin/login", data=dict(email="owner@example.com", password="password", csrf_token=token))
    _, missing_csrf = await app.asgi_client.post(f"/admin/orders/{order_id}/refund", data={})
    assert missing_csrf.status == 403
    path = f"/admin/orders/{order_id}/refund"
    form = dict(csrf_token=token, refund_key=str(uuid4()), amount="4.00", reason="Damaged",
                reference="cash-return-1", confirmed="on")
    _, first = await app.asgi_client.post(path, data=form)
    assert first.status == 302
    _, duplicate = await app.asgi_client.post(path, data=form)
    assert duplicate.status == 302
    _, too_much = await app.asgi_client.post(path, data={**form, "refund_key": str(uuid4()), "amount": "6.01"})
    assert too_much.status == 409
    async with session_scope() as db:
        order = await db.get(Order, order_id)
        assert order.status == "paid"
        listing = await db.get(FlowerListing, listing_id)
        assert listing.quantity_available == 5
    _, remaining = await app.asgi_client.post(path, data={**form, "refund_key": str(uuid4()),
                                                      "amount": "6.00", "reference": "cash-return-2"})
    assert remaining.status == 302
    async with session_scope() as db:
        order = await db.get(Order, order_id)
        refunds = (await db.scalars(select(OrderRefund))).all()
        movements = (await db.scalars(select(InventoryMovement))).all()
        assert order.status == "refunded" and len(refunds) == 2
        assert sum(row.amount_cents for row in refunds) == 1000
        assert movements == []
    _, detail = await app.asgi_client.get(f"/admin/orders/{order_id}")
    assert detail.status == 200 and "Payment refunds" in detail.text
    _, ledger = await app.asgi_client.get("/admin/reports/sales?format=csv")
    assert ledger.status == 200 and "Recorded refunded USD" in ledger.text
    assert "10.00,10.00,0.00" in ledger.text


@pytest.mark.asyncio
async def test_stripe_refund_uncertain_outcome_blocks_retries(monkeypatch):
    from app import refunds
    import stripe
    order_id, _ = await make_order("stripe_checkout")
    monkeypatch.setattr(refunds, "get_settings", lambda: SimpleNamespace(stripe_secret_key="sk_test_fake"))
    calls = []
    def fail(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("network failed after sending")
    monkeypatch.setattr(stripe.Refund, "create", fail)
    form = dict(refund_key=str(uuid4()), amount="4.00", reason="Requested")
    with pytest.raises(ValueError, match="uncertain"):
        await issue_refund(order_id, form, 1)
    assert calls[0]["amount"] == 400 and calls[0]["payment_intent"] == "pi_test"
    existing = await issue_refund(order_id, form, 1)
    assert existing.status == "review" and len(calls) == 1
    with pytest.raises(ValueError, match="prior refund"):
        await issue_refund(order_id, {**form, "refund_key": str(uuid4())}, 1)


@pytest.mark.asyncio
async def test_stripe_checkout_partial_refund_then_full_webhook(monkeypatch):
    from app import refunds
    from app.payments import apply_checkout_event
    import stripe
    order_id, listing_id = await make_order("stripe_checkout")
    monkeypatch.setattr(refunds, "get_settings", lambda: SimpleNamespace(stripe_secret_key="sk_test_fake"))
    calls = []
    def succeed(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(id=f"re_test_{len(calls)}", status="succeeded")
    monkeypatch.setattr(stripe.Refund, "create", succeed)
    first = await issue_refund(order_id, dict(refund_key=str(uuid4()), amount="4.00", reason="Damaged"), 1)
    assert first.status == "succeeded" and first.reference == "re_test_1"
    assert calls[0]["amount"] == 400 and calls[0]["metadata"]["order_id"] == str(order_id)
    async with session_scope() as db:
        order = await db.get(Order, order_id)
        assert order.status == "paid"
    partial_event = {"id": "evt_partial", "type": "charge.refunded", "data": {"object": {
        "id": "ch_test", "payment_intent": "pi_test", "currency": "usd", "amount": 1000,
        "amount_refunded": 400}}}
    assert await apply_checkout_event(partial_event) == "applied"
    assert await apply_checkout_event(partial_event) == "ignored"
    async with session_scope() as db:
        assert (await db.get(Order, order_id)).status == "paid"
    # The signed full-charge event may arrive before the Refund.create response.
    event = {"id": "evt_refunded", "type": "charge.refunded", "data": {"object": {
        "id": "ch_test", "payment_intent": "pi_test", "currency": "usd", "amount": 1000,
        "amount_refunded": 1000}}}
    assert await apply_checkout_event(event) == "applied"
    assert await apply_checkout_event(event) == "ignored"
    assert await apply_checkout_event(partial_event) == "ignored"
    async with session_scope() as db:
        order = await db.get(Order, order_id)
        listing = await db.get(FlowerListing, listing_id)
        entries = (await db.scalars(select(OrderRefund).where(OrderRefund.order_id == order_id))).all()
        assert order.status == "refunded" and listing.quantity_available == 5
        assert sum(row.amount_cents for row in entries) == 1000
    with pytest.raises(ValueError, match="Only a paid order"):
        await issue_refund(order_id, dict(refund_key=str(uuid4()), amount="1.00", reason="Again"), 1)
