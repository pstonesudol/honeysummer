import json

import pytest
from sqlalchemy import func, select

from app import emails
from app.db import session_scope
from app.models import Inquiry
from app.server import app


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
    from app.settings import get_settings

    monkeypatch.setattr(get_settings(), "media_root", tmp_path)

    _, response = await app.asgi_client.post(
        "/api/inquiries/",
        data=_form(kind="wedding"),
        files={"photo": ("inspo.jpg", b"image-bytes", "image/jpeg")},
    )

    assert response.status == 201
    async with session_scope() as session:
        inquiry = (await session.execute(select(Inquiry))).scalar_one()
    assert inquiry.photo.startswith("inquiries/")
    assert response.json["photo"].endswith(inquiry.photo)


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
