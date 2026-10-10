from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import reconcile as reconciliation_cli
from app.admin import CSRF_COOKIE
from app.auth import hash_password
from app.correspondence import parse_email
from app.db import session_scope
from app.migrate_inquiry_photos import migrate
from app.models import AdminActivity, GalleryImage, Inquiry, InquiryCorrespondence, Order, OrderItem, User
from app.server import app
from app.settings import get_settings
from app.verify_phase9 import verify

EMAIL = (
    b"From: ava@example.com\r\nTo: owner@example.com\r\nSubject: Flower colors\r\n"
    b"Date: Fri, 9 Oct 2026 12:00:00 -0400\r\nMessage-ID: <one@example.com>\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n\r\nPink and cream, please."
)


def test_email_import_validates_customer_date_and_plain_text():
    values = parse_email(EMAIL, "ava@example.com", "received")
    assert values["summary"] == "Pink and cream, please."
    assert values["occurred_at"] == datetime(2026, 10, 9, 16, tzinfo=UTC)
    assert values["source_id"] == parse_email(EMAIL, "ava@example.com", "received")["source_id"]
    with pytest.raises(ValueError, match="does not match"):
        parse_email(EMAIL, "other@example.com", "received")
    with pytest.raises(ValueError):
        parse_email(EMAIL.replace(b"Fri, 9 Oct 2026 12:00:00 -0400", b"invalid"), "ava@example.com", "received")


@pytest.mark.asyncio
async def test_synthetic_verification_rejects_live_keys_and_nondevelopment_environment(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_live_never_use")
    with pytest.raises(ValueError, match="Only sk_test_"):
        await verify(apply=True)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_mock")
    monkeypatch.setattr(settings, "debug", False)
    with pytest.raises(ValueError, match="nonproduction"):
        await verify(apply=True)


async def login():
    async with session_scope() as db:
        db.add(User(email="owner@example.com", password_hash=hash_password("password"), is_admin=True))
        await db.commit()
    await app.asgi_client.get("/admin/login")
    csrf = app.asgi_client.cookies.get(CSRF_COOKIE)
    await app.asgi_client.post(
        "/admin/login", data=dict(email="owner@example.com", password="password", csrf_token=csrf)
    )


@pytest.mark.asyncio
async def test_account_activity_and_photo_selection_require_admin_and_keep_secrets_out():
    for url in ("/admin/account", "/admin/activity"):
        _, response = await app.asgi_client.get(url)
        assert response.status == 302
    await login()
    async with session_scope() as db:
        photo = GalleryImage(image="gallery/flowers.jpg", alt_text="Pink flowers", focal_x=20, focal_y=70)
        db.add(photo)
        await db.commit()
        photo_id = photo.id
    _, page = await app.asgi_client.get("/admin/site-content")
    assert "Home hero" in page.text and "Pink flowers" in page.text
    csrf = app.asgi_client.cookies.get(CSRF_COOKIE)
    _, saved = await app.asgi_client.post(
        "/admin/site-content", data=dict(csrf_token=csrf, photo_home=str(photo_id), homeIntro="Private form value")
    )
    assert saved.status == 302
    _, public = await app.asgi_client.get("/api/site-content/")
    assert public.json["content"]["photos"]["home"]["alt_text"] == "Pink flowers"
    _, account = await app.asgi_client.get("/admin/account")
    assert account.status == 200 and "owner@example.com" in account.text
    _, activity = await app.asgi_client.get("/admin/activity")
    assert activity.status == 200 and "/admin/site-content" in activity.text
    assert "Private form value" not in activity.text and "password_hash" not in account.text
    async with session_scope() as db:
        assert await db.scalar(select(AdminActivity.id))


@pytest.mark.asyncio
async def test_local_photo_migration_is_dry_run_first_and_removes_only_verified_original(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "media_root", tmp_path / "public")
    monkeypatch.setattr(settings, "private_media_root", tmp_path / "private")
    for name in (
        "r2_bucket",
        "r2_private_bucket",
        "r2_endpoint_url",
        "r2_public_url",
        "r2_access_key_id",
        "r2_secret_access_key",
    ):
        monkeypatch.setattr(settings, name, "")
    source = settings.media_root / "inquiries/2026/old.png"
    source.parent.mkdir(parents=True)
    body = b"\x89PNG\r\n\x1a\nphoto"
    source.write_bytes(body)
    async with session_scope() as db:
        inquiry = Inquiry(kind="wedding", name="Ava", email="ava@example.com", photo="inquiries/2026/old.png")
        db.add(inquiry)
        await db.commit()
        pk = inquiry.id
    assert "would migrate" in (await migrate())[0] and source.exists()
    assert "public original removed" in (await migrate(apply=True))[0]
    assert not source.exists()
    async with session_scope() as db:
        inquiry = await db.get(Inquiry, pk)
        assert (settings.private_media_root / inquiry.photo).read_bytes() == body
    assert "already private" in (await migrate())[0]


@pytest.mark.asyncio
async def test_email_import_route_is_csrf_protected_and_idempotent():
    await login()
    async with session_scope() as db:
        inquiry = Inquiry(kind="wedding", name="Ava", email="ava@example.com")
        db.add(inquiry)
        await db.commit()
        pk = inquiry.id
    await app.asgi_client.get(f"/admin/inquiries/{pk}")
    csrf = app.asgi_client.cookies.get(CSRF_COOKIE)
    url = f"/admin/inquiries/{pk}/import-email"
    _, denied = await app.asgi_client.post(
        url, data={"direction": "received"}, files={"email_file": ("email.eml", EMAIL, "message/rfc822")}
    )
    assert denied.status == 403
    for _ in range(2):
        _, imported = await app.asgi_client.post(
            url,
            data={"direction": "received", "csrf_token": csrf},
            files={"email_file": ("email.eml", EMAIL, "message/rfc822")},
        )
        assert imported.status == 302
    async with session_scope() as db:
        rows = (await db.scalars(select(InquiryCorrespondence))).all()
        assert len(rows) == 1 and rows[0].summary == "Pink and cream, please."


@pytest.mark.asyncio
async def test_daily_preparation_includes_only_paid_scheduled_incomplete_work():
    await login()
    async with session_scope() as db:
        for status, state, name in (
            ("paid", "new", "Prepare these flowers"),
            ("pending", "new", "Unpaid hidden"),
            ("paid", "completed", "Completed hidden"),
        ):
            db.add(
                Order(
                    status=status,
                    fulfillment_state=state,
                    fulfillment_date=date(2026, 10, 10),
                    items=[OrderItem(name_snapshot=name, price_snapshot=Decimal("2.00"), quantity=3)],
                )
            )
        await db.commit()
    _, page = await app.asgi_client.get("/admin/orders/preparation?date=2026-10-10")
    assert page.status == 200 and "Prepare these flowers" in page.text
    assert "Unpaid hidden" not in page.text and "Completed hidden" not in page.text


@pytest.mark.asyncio
async def test_reconciliation_persists_findings_on_the_same_event_loop(monkeypatch):
    async def fake_reconcile(**kwargs):
        return ["Synthetic finding"]

    monkeypatch.setattr(reconciliation_cli, "reconcile", fake_reconcile)
    assert await reconciliation_cli.reconcile_and_record(apply=False, full=True) == ["Synthetic finding"]
