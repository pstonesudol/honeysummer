from decimal import Decimal
from types import SimpleNamespace

import pytest
import stripe
from sqlalchemy import select

from app.admin import CSRF_COOKIE, _proposal_form
from app.auth import hash_password
from app.db import session_scope
from app.models import BouquetProposal, FlowerListing, Inquiry, InventoryMovement, Order, OrderItem, User
from app.proposals import apply_invoice_event, send_invoice, update_sent_invoice, validate_draft
from app.server import app
from app.settings import get_settings


def draft(listing_id=None):
    return validate_draft(
        dict(
            title="Garden bouquet",
            description="Seasonal flowers",
            terms="Substitutions allowed",
            fulfillment="delivery",
            location="Main Street, Friday",
            delivery="3.25",
            lines=[
                dict(name="Dahlias", description="Pink", quantity=2, price="12.50", listing_id=listing_id),
                dict(name="Design labor", description="", quantity=1, price="10.00"),
            ],
        )
    )


@pytest.mark.asyncio
async def test_only_bouquet_inquiries_offer_proposals_and_csrf():
    async with session_scope() as db:
        db.add(User(email="owner@example.com", password_hash=hash_password("password"), is_admin=True))
        db.add_all([Inquiry(kind=kind, name="Buyer", email="buyer@example.com") for kind in ("bouquet", "wedding")])
        await db.commit()
    _, anonymous = await app.asgi_client.get("/admin/proposals/")
    assert anonymous.status == 302
    await app.asgi_client.get("/admin/login")
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    await app.asgi_client.post(
        "/admin/login", data=dict(email="owner@example.com", password="password", csrf_token=token)
    )
    _, rejected = await app.asgi_client.get("/admin/proposals/from-inquiry/2")
    assert rejected.status == 404
    _, start = await app.asgi_client.get("/admin/proposals/from-inquiry/1")
    assert start.status == 200
    _, no_csrf = await app.asgi_client.post("/admin/proposals/from-inquiry/1", data={})
    assert no_csrf.status == 403
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    _, created = await app.asgi_client.post("/admin/proposals/from-inquiry/1", data={"csrf_token": token})
    assert created.status == 302
    _, page = await app.asgi_client.get("/admin/proposals/1")
    assert page.status == 200
    assert "Customer-facing preview" not in page.text
    assert page.text.count('data-proposal-line="1"') == 1
    assert 'id="add-proposal-line"' in page.text
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    _, saved = await app.asgi_client.post(
        "/admin/proposals/1/save",
        data={
            "csrf_token": token,
            "title": "Garden bouquet",
            "description": "Seasonal flowers",
            "terms": "Substitutions allowed",
            "fulfillment": "delivery",
            "location": "Main Street, Friday",
            "delivery": "3.25",
            "name_1": "Dahlias",
            "quantity_1": "2",
            "price_1": "12.50",
            "name_2": "Design labor",
            "quantity_2": "1",
            "price_2": "10.00",
            "internal_notes": "Not shown to customer",
        },
    )
    assert saved.status == 302
    _, preview = await app.asgi_client.get("/admin/proposals/1")
    assert preview.status == 200
    assert "Customer-facing preview" in preview.text
    assert "$38.25" in preview.text
    assert "Not shown to customer" in preview.text  # draft-only notes, outside the customer preview
    assert preview.text.count('data-proposal-line="2"') == 1
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    fields = dict(
        csrf_token=token,
        title="Garden bouquet",
        description="Seasonal flowers",
        terms="Substitutions allowed",
        fulfillment="pickup",
        location="Farm",
        line_ids="1,3,4,5,6,7,8",
    )
    for index in (1, 3, 4, 5, 6, 7, 8):
        fields.update({f"name_{index}": f"Arrangement {index}", f"quantity_{index}": "1", f"price_{index}": "1.00"})
    _, saved = await app.asgi_client.post("/admin/proposals/1/save", data=fields)
    assert saved.status == 302
    _, preview = await app.asgi_client.get("/admin/proposals/1")
    assert preview.text.count('data-proposal-line="7"') == 1
    assert preview.text.count("Arrangement 8") >= 1
    async with session_scope() as db:
        proposal = await db.get(BouquetProposal, 1)
        assert len(proposal.draft["lines"]) == 7 and proposal.draft["total_cents"] == 700
    fields["price_8"] = "not-a-price"
    fields["csrf_token"] = app.asgi_client.cookies.get(CSRF_COOKIE)
    _, invalid = await app.asgi_client.post(
        "/admin/proposals/1/save", data=fields, headers={"accept": "application/json"}
    )
    assert invalid.status == 400 and invalid.json["field"] == "price_8"


def test_dynamic_proposal_lines_validate_every_selected_row():
    form = dict(
        title="Retail flowers",
        description="Spring",
        terms="Substitutions allowed",
        fulfillment="pickup",
        location="Farm",
        line_ids="1,3,4,5,6,7,8",
    )
    for index in (1, 3, 4, 5, 6, 7, 8):
        form.update({f"name_{index}": f"Flower {index}", f"quantity_{index}": "1", f"price_{index}": "1.00"})
    form["name_2"] = "Deleted row"
    lines = validate_draft(_proposal_form(form))["lines"]
    assert len(lines) == 7 and all(line["name"] != "Deleted row" for line in lines)
    form["name_8"] = ""
    with pytest.raises(ValueError, match="Name each proposal line"):
        _proposal_form(form)
    form["name_8"] = "Flower 8"
    form["line_ids"] = "1,1"
    with pytest.raises(ValueError, match="distinct"):
        _proposal_form(form)
    form["line_ids"] = ",".join(str(i) for i in range(1, 202))
    with pytest.raises(ValueError, match="200"):
        _proposal_form(form)


def test_amount_validation():
    assert draft()["total_cents"] == 3825
    for price in ("NaN", "1.001", "-1"):
        with pytest.raises(ValueError):
            validate_draft(
                dict(
                    title="A",
                    description="B",
                    terms="C",
                    fulfillment="pickup",
                    location="Here",
                    lines=[dict(name="Flower", quantity=1, price=price)],
                )
            )
    with pytest.raises(ValueError, match="500 characters"):
        validate_draft(
            dict(
                title="A",
                description="B",
                terms="C",
                fulfillment="pickup",
                location="Here",
                lines=[dict(name="Flower", description="x" * 500, quantity=1, price="1.00")],
            )
        )


@pytest.mark.asyncio
async def test_send_pay_and_duplicate_webhook_preserve_stock(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_mock")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_mock")
    monkeypatch.setattr(stripe.Customer, "create", lambda **kw: SimpleNamespace(id="cus_1"))
    invoices, items = [], []

    def create_invoice(**kwargs):
        invoices.append(kwargs)
        return SimpleNamespace(id="in_1")

    def create_item(**kwargs):
        items.append(kwargs)
        return SimpleNamespace(id="ii_1")

    monkeypatch.setattr(stripe.Invoice, "create", create_invoice)
    monkeypatch.setattr(stripe.InvoiceItem, "create", create_item)
    monkeypatch.setattr(
        stripe.Invoice, "finalize_invoice", lambda *args, **kw: SimpleNamespace(id="in_1", total=3825, currency="usd")
    )
    monkeypatch.setattr(
        stripe.Invoice,
        "send_invoice",
        lambda *args, **kw: SimpleNamespace(
            id="in_1", hosted_invoice_url="https://invoice.stripe.com/test", number="HS-1"
        ),
    )
    async with session_scope() as db:
        listing = FlowerListing(
            name="Dahlias", price=Decimal("12.50"), quantity_available=3, channel="retail", active=True
        )
        db.add(listing)
        await db.flush()
        inquiry = Inquiry(kind="bouquet", name="Buyer", email="buyer@example.com", phone="123")
        db.add(inquiry)
        await db.flush()
        proposal = BouquetProposal(
            inquiry_id=inquiry.id, status="draft", draft=draft(listing.id), history=[], internal_notes="private"
        )
        db.add(proposal)
        await db.commit()
        proposal_id = proposal.id
    await send_invoice(proposal_id)
    assert len(invoices[0]["description"]) <= 500
    assert sum(item.get("amount", 0) for item in items) == 325
    assert sum(item.get("quantity", 0) * int(item.get("unit_amount_decimal", 0)) for item in items) == 3500
    assert any(item["description"].startswith("Terms:") for item in items)
    with pytest.raises(ValueError):
        await send_invoice(proposal_id)
    async with session_scope() as db:
        assert (await db.get(FlowerListing, 1)).quantity_available == 3
    event = dict(
        id="evt_paid_1",
        type="invoice.paid",
        data={
            "object": dict(id="in_1", currency="usd", total=3825, amount_paid=3825, amount_remaining=0, status="paid")
        },
    )
    assert await apply_invoice_event(event) == "applied"
    assert await apply_invoice_event(event) == "ignored"
    async with session_scope() as db:
        assert (await db.get(FlowerListing, 1)).quantity_available == 1
        assert (await db.get(BouquetProposal, proposal_id)).status == "paid"
        assert len((await db.scalars(select(Order))).all()) == 1
        assert len((await db.scalars(select(OrderItem))).all()) == 1
        assert [m.kind for m in (await db.scalars(select(InventoryMovement).order_by(InventoryMovement.id))).all()] == [
            "opening",
            "reserve",
            "sale",
        ]


@pytest.mark.asyncio
async def test_paid_with_insufficient_stock_requires_review_without_booking():
    async with session_scope() as db:
        listing = FlowerListing(name="Dahlias", price=Decimal("12.50"), quantity_available=1)
        inquiry = Inquiry(kind="bouquet", name="Buyer", email="buyer@example.com")
        db.add_all([listing, inquiry])
        await db.flush()
        snapshot = draft(listing.id)
        db.add(
            BouquetProposal(
                inquiry_id=inquiry.id,
                status="sent",
                draft=snapshot,
                history=[dict(version=1, draft=snapshot, invoice_id="in_2")],
                stripe_invoice_id="in_2",
                internal_notes="",
            )
        )
        await db.commit()
    outcome = await apply_invoice_event(
        dict(
            id="evt_short",
            type="invoice.paid",
            data={
                "object": dict(
                    id="in_2", currency="usd", total=3825, amount_paid=3825, amount_remaining=0, status="paid"
                )
            },
        )
    )
    assert outcome == "review"
    async with session_scope() as db:
        assert (await db.get(BouquetProposal, 1)).status == "stock_review"
        assert (await db.get(FlowerListing, 1)).quantity_available == 1
        assert not (await db.scalars(select(Order))).all()


@pytest.mark.asyncio
async def test_invoice_mismatch_and_out_of_band_payment_are_not_booked():
    async with session_scope() as db:
        inquiry = Inquiry(kind="bouquet", name="Buyer", email="buyer@example.com")
        db.add(inquiry)
        await db.flush()
        snapshot = draft()
        db.add(
            BouquetProposal(
                inquiry_id=inquiry.id,
                status="sent",
                draft=snapshot,
                history=[dict(version=1, draft=snapshot, invoice_id="in_mismatch")],
                stripe_invoice_id="in_mismatch",
                internal_notes="",
            )
        )
        await db.commit()
    for changes in ({"total": 2000}, {"paid_out_of_band": True}, {"amount_paid": 0}):
        invoice = dict(
            id="in_mismatch", currency="usd", total=3825, amount_paid=3825, amount_remaining=0, status="paid"
        )
        invoice.update(changes)
        assert (
            await apply_invoice_event(dict(id="evt_mismatch", type="invoice.paid", data={"object": invoice}))
            == "review"
        )
    async with session_scope() as db:
        assert (await db.get(BouquetProposal, 1)).status == "sent"
        assert not (await db.scalars(select(Order))).all()


@pytest.mark.asyncio
async def test_revision_voids_only_open_invoice_and_preserves_snapshot(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_mock")
    async with session_scope() as db:
        inquiry = Inquiry(kind="bouquet", name="Buyer", email="buyer@example.com")
        db.add(inquiry)
        await db.flush()
        snapshot = draft()
        db.add(
            BouquetProposal(
                inquiry_id=inquiry.id,
                status="sent",
                draft=snapshot,
                history=[dict(version=1, draft=snapshot, invoice_id="in_old")],
                stripe_invoice_id="in_old",
                invoice_url="https://invoice.stripe.com/old",
                internal_notes="",
            )
        )
        await db.commit()
    monkeypatch.setattr(stripe.Invoice, "retrieve", lambda *args: SimpleNamespace(status="paid"))
    with pytest.raises(ValueError):
        await update_sent_invoice(1, "revise")
    monkeypatch.setattr(stripe.Invoice, "retrieve", lambda *args: SimpleNamespace(status="open"))
    monkeypatch.setattr(stripe.Invoice, "void_invoice", lambda *args: SimpleNamespace(status="void"))
    await update_sent_invoice(1, "revise")
    async with session_scope() as db:
        proposal = await db.get(BouquetProposal, 1)
        assert proposal.status == "draft"
        assert proposal.stripe_invoice_id is None
        assert proposal.history[0]["invoice_id"] == "in_old"
        assert proposal.draft == snapshot
