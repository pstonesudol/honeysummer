import json

import pytest
from sqlalchemy import func, select

from app import emails
from app.admin import CSRF_COOKIE
from app.auth import hash_password
from app.db import session_scope
from app.models import Inquiry, InquiryCorrespondence, User
from app.server import app
from app.settings import get_settings


@pytest.fixture
def sent(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(emails, "send_email", lambda **kwargs: calls.append(kwargs))
    return calls


def _form(**overrides) -> dict:
    data = {
        "kind": "bouquet",
        "name": "Jamie Rivera",
        "email": "jamie@example.com",
        "phone": "570-555-0100",
        "message": "A cheerful bouquet, please.",
        "details": json.dumps(
            {
                "fulfillment": "pickup",
                "occasion": "Birthday",
                "seasonal_substitutions": True,
            }
        ),
    }
    data.update(overrides)
    return data


async def _inquiry_count() -> int:
    async with session_scope() as session:
        return (await session.execute(select(func.count()).select_from(Inquiry))).scalar_one()


@pytest.mark.asyncio
async def test_creates_inquiry_and_sends_two_emails(sent):
    _, response = await app.asgi_client.post("/api/inquiries/", data=_form())

    assert response.status == 201
    async with session_scope() as session:
        inquiry = (await session.execute(select(Inquiry))).scalar_one()
    assert inquiry.kind == "bouquet"
    assert inquiry.details["occasion"] == "Birthday"
    assert inquiry.details["seasonal_substitutions"] is True
    assert len(sent) == 2
    assert sent[0]["to"] == "hello@hellohoneysummer.com"
    assert sent[0]["reply_to"] == "jamie@example.com"
    assert sent[1]["to"] == "jamie@example.com"


@pytest.mark.asyncio
async def test_accepts_an_inspiration_photo(sent, monkeypatch, tmp_path):

    monkeypatch.setattr(get_settings(), "private_media_root", tmp_path)

    _, response = await app.asgi_client.post(
        "/api/inquiries/",
        data=_form(kind="wedding"),
        files={"photo": ("inspo.jpg", b"\xff\xd8\xffimage-bytes", "image/jpeg")},
    )

    assert response.status == 201
    async with session_scope() as session:
        inquiry = (await session.execute(select(Inquiry))).scalar_one()
    assert inquiry.photo.startswith("inquiries/")
    assert response.json["photo"] == "Received privately; visible only to the shop owner."
    assert (tmp_path / inquiry.photo).exists()
    _, anonymous = await app.asgi_client.get(f"/admin/inquiries/{inquiry.id}/photo")
    assert anonymous.status == 302

    async with session_scope() as session:
        session.add(User(email="owner@example.com", password_hash=hash_password("password"), is_admin=True))
        await session.commit()
    await app.asgi_client.get("/admin/login")
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    await app.asgi_client.post(
        "/admin/login", data=dict(email="owner@example.com", password="password", csrf_token=token)
    )
    _, photo = await app.asgi_client.get(f"/admin/inquiries/{inquiry.id}/photo")
    assert photo.status == 200 and photo.body == b"\xff\xd8\xffimage-bytes"
    assert photo.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_inquiry_email_failure_is_visible_and_other_message_still_attempted(monkeypatch):

    sent = []

    def send(**kwargs):
        sent.append(kwargs["to"])
        if kwargs["to"] == "hello@hellohoneysummer.com":
            raise RuntimeError("mail provider unavailable")

    monkeypatch.setattr(emails, "send_email", send)
    monkeypatch.setattr(get_settings(), "resend_api_key", "test-key")
    _, response = await app.asgi_client.post("/api/inquiries/", data=_form())
    assert response.status == 201
    assert sent == ["hello@hellohoneysummer.com", "jamie@example.com"]
    async with session_scope() as db:
        inquiry = (await db.scalars(select(Inquiry))).one()
        assert inquiry.email_delivery == {"farm": "failed", "customer": "accepted"}
        entries = (await db.scalars(select(InquiryCorrespondence))).all()
        assert len(entries) == 1 and entries[0].actor_id is None
        db.add(User(email="owner@example.com", password_hash=hash_password("password"), is_admin=True))
        await db.commit()
    await app.asgi_client.get("/admin/login")
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    await app.asgi_client.post(
        "/admin/login", data=dict(email="owner@example.com", password="password", csrf_token=token)
    )
    _, attention = await app.asgi_client.get("/admin/operations/attention")
    assert attention.status == 200 and "Failed inquiry emails" in attention.text
    assert "farm: failed" in attention.text and "customer: accepted" in attention.text


@pytest.mark.asyncio
async def test_rejects_a_missing_email(sent):
    _, response = await app.asgi_client.post("/api/inquiries/", data=_form(email=""))

    assert response.status == 400
    assert "email" in response.json
    assert await _inquiry_count() == 0


@pytest.mark.asyncio
async def test_wholesale_access_requests_must_use_signup(sent):
    _, response = await app.asgi_client.post("/api/inquiries/", data=_form(kind="wholesale"))
    assert response.status == 400
    assert await _inquiry_count() == 0
