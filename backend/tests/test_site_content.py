from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.admin import CSRF_COOKIE
from app.auth import hash_password
from app.db import session_scope
from app.models import Announcement, SiteContent, User
from app.server import app


@pytest.mark.asyncio
async def test_content_editor_requires_admin_and_preserves_original_copy_until_saved():
    _, public = await app.asgi_client.get("/api/site-content/")
    assert public.status == 200 and public.json == {"content": {}}
    _, locked = await app.asgi_client.get("/admin/site-content")
    assert locked.status == 302
    async with session_scope() as db:
        db.add(User(email="owner@example.com", password_hash=hash_password("password"), is_admin=True))
        await db.commit()
    await app.asgi_client.get("/admin/login")
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    await app.asgi_client.post(
        "/admin/login", data=dict(email="owner@example.com", password="password", csrf_token=token)
    )
    _, form = await app.asgi_client.get("/admin/site-content")
    assert form.status == 200 and "Website text" in form.text
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    _, denied = await app.asgi_client.post("/admin/site-content", data={"location": "Elsewhere"})
    assert denied.status == 403
    _, invalid = await app.asgi_client.post(
        "/admin/site-content", data=dict(csrf_token=token, instagram="javascript:alert(1)", location="Elsewhere")
    )
    assert invalid.status == 400
    _, saved = await app.asgi_client.post(
        "/admin/site-content",
        data=dict(
            csrf_token=token,
            location="=Garden town",
            faq_question_1="How do I pick up?",
            faq_answer_1="By arrangement.",
        ),
    )
    assert saved.status == 302
    _, public = await app.asgi_client.get("/api/site-content/")
    assert public.json["content"]["location"] == "=Garden town"
    assert public.json["content"]["faq"] == [{"question": "How do I pick up?", "answer": "By arrangement."}]
    async with session_scope() as db:
        assert (await db.get(SiteContent, 1)).updated_by == 1


@pytest.mark.asyncio
async def test_scheduled_announcements_respect_eastern_dates_and_safe_links():
    today = datetime.now(ZoneInfo("America/New_York")).date()
    async with session_scope() as db:
        db.add(User(email="owner@example.com", password_hash=hash_password("password"), is_admin=True))
        db.add_all(
            [
                Announcement(text="Current", active=True, starts_on=today, ends_on=today),
                Announcement(text="Future", active=True, starts_on=today + timedelta(days=1)),
                Announcement(text="Past", active=True, ends_on=today - timedelta(days=1)),
            ]
        )
        await db.commit()
    _, visible = await app.asgi_client.get("/api/announcement/")
    assert visible.json["announcement"]["text"] == "Current"
    await app.asgi_client.get("/admin/login")
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    await app.asgi_client.post(
        "/admin/login", data=dict(email="owner@example.com", password="password", csrf_token=token)
    )
    await app.asgi_client.get("/admin/announcements/new")
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    _, unsafe = await app.asgi_client.post(
        "/admin/announcements/new", data=dict(csrf_token=token, text="Unsafe", link_url="javascript:alert(1)")
    )
    assert unsafe.status == 400
    _, backwards = await app.asgi_client.post(
        "/admin/announcements/new",
        data=dict(
            csrf_token=token,
            text="Backwards",
            starts_on=(today + timedelta(days=1)).isoformat(),
            ends_on=today.isoformat(),
        ),
    )
    assert backwards.status == 400
