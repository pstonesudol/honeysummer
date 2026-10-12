"""Branded transactional emails retain text, safe content and routing."""

from base64 import b64decode
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app import emails
from app.db import session_scope
from app.models import Inquiry
from app.security import deliver_security_mail, queue_mail
from app.security_models import SecurityMail
from app.settings import get_settings


@pytest.fixture
def provider(monkeypatch):
    calls = []
    settings = get_settings()
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "public_origin", "https://staging.example.com")
    monkeypatch.setattr(settings, "inquiry_notification_email", "farm@example.com")
    monkeypatch.setattr(emails.resend.Emails, "send", lambda *args: calls.append(args))
    return calls


def test_plain_messages_gain_branding_and_inline_logo(provider):
    body = 'Hello <script>alert("test")</script>\n\nOne\nTwo'
    emails.send_email(subject="A note & more", body=body, to="customer@example.com")

    params = provider[0][0]
    assert params["text"] == body
    assert params["to"] == ["customer@example.com"]
    assert "A note &amp; more" in params["html"]
    assert "<script>" not in params["html"]
    assert "&lt;script&gt;" in params["html"]
    assert "One<br>Two" in params["html"]
    assert 'href="https://staging.example.com"' in params["html"]
    for color in ("#f6f2ea", "#d7b3b6", "#e6cfae", "#6a4e42"):
        assert color in params["html"]
    attachment = params["attachments"][0]
    assert f"cid:{attachment['content_id']}" in params["html"]
    assert attachment["content_type"] == "image/png"
    logo = Path(__file__).resolve().parents[2] / "frontend/public/brand/honey-summer-logo.png"
    assert b64decode(attachment["content"]) == logo.read_bytes()


def test_explicit_html_and_idempotency_are_preserved(provider):
    emails.send_email(
        subject="Security message",
        body="Plain fallback",
        html_body="<p>Existing secure link</p>",
        to="customer@example.com",
        reply_to="farm@example.com",
        idempotency_key="security-mail-1",
    )
    params, options = provider[0]
    assert params["html"] == "<p>Existing secure link</p>"
    assert params["text"] == "Plain fallback"
    assert params["reply_to"] == "farm@example.com"
    assert "attachments" not in params
    assert options == {"idempotency_key": "security-mail-1"}


@pytest.mark.parametrize("channel", ["retail", "wholesale"])
@pytest.mark.parametrize("fulfillment", ["pickup", "delivery"])
def test_order_summary_totals_details_and_routing(provider, channel, fulfillment):
    emails.send_order_emails(
        order_id=7,
        fulfillment=fulfillment,
        pickup_window="Saturday, 10–12" if fulfillment == "pickup" else "",
        delivery_address="12 Garden Lane\nMountain Top, PA" if fulfillment == "delivery" else "",
        customer_email="customer@example.com",
        customer_name="Dana <Bloom>",
        items=[{"quantity": 3, "name": "Roses & dahlias", "price": "5.10"}],
        channel=channel,
        delivery_fee=Decimal("2.50") if fulfillment == "delivery" else 0,
    )
    assert len(provider) == 2
    customer, farm = (call[0] for call in provider)
    markup = customer["html"]
    assert "HS000007" in markup
    assert "Thank you for your order." in markup
    assert "Dana &lt;Bloom&gt;" in markup
    assert "Roses &amp; dahlias" in markup
    assert "$5.10 each" in markup
    assert "$15.30" in markup
    assert ("$17.80" if fulfillment == "delivery" else "$15.30") in markup
    assert f"{fulfillment.capitalize()} details" in markup
    if fulfillment == "delivery":
        assert "$2.50" in markup
        assert "12 Garden Lane<br>Mountain Top, PA" in markup
    else:
        assert "Saturday, 10–12" in markup
    assert "A new order has arrived." in farm["html"]
    assert "customer@example.com" in farm["html"]
    assert customer["reply_to"] == "farm@example.com"
    assert farm["reply_to"] == "customer@example.com"
    assert customer["to"] == ["customer@example.com"]
    assert farm["to"] == ["farm@example.com"]
    assert "Isabella will be in touch" in customer["text"]
    assert "With warmth,\nHoney Summer" in customer["text"]
    assert customer["attachments"][0]["content_id"] == "honey-summer-logo"


def test_recipient_specific_order_send(provider):
    emails.send_order_emails(
        order_id=7,
        order_reference="CUSTOM-7",
        fulfillment="pickup",
        pickup_window="",
        delivery_address="",
        customer_email="customer@example.com",
        items=[{"quantity": 1, "name": "Flowers", "price": "5.00"}],
        recipient="farm",
    )
    assert len(provider) == 1
    assert "CUSTOM-7" in provider[0][0]["html"]
    assert provider[0][0]["to"] == ["farm@example.com"]


@pytest.mark.parametrize("kind", ["bouquet", "wedding", "contact", "wholesale"])
def test_all_inquiry_emails_use_shared_template(provider, kind):
    inquiry = Inquiry(
        id=1, kind=kind, name="Dana <Bloom>", email="customer@example.com", message="Flowers & more", details={}
    )
    emails.send_inquiry_emails(inquiry)
    assert len(provider) == 2
    for (params,) in provider:
        assert "cid:honey-summer-logo" in params["html"]
        assert "Dana &lt;Bloom&gt;" in params["html"]
        assert "With warmth, Honey Summer" in params["html"]
        assert params["attachments"]


def test_wholesale_notifications_use_shared_template(provider):
    emails.send_signup_notification(business_name="Fern & Fig", email="customer@example.com", contact_name="Dana")
    emails.send_wholesale_approval_email(email="customer@example.com")
    assert len(provider) == 2
    for (params,) in provider:
        assert "cid:honey-summer-logo" in params["html"]
        assert "With warmth, Honey Summer" in params["html"]
        assert params["attachments"]


@pytest.mark.parametrize(
    "subject",
    [
        "Account Access Updated",
        "Reset Your Password",
        "Confirm Email Change",
        "Staff Invitation",
        "Temporary Password Set",
        "Application Received",
        "Wholesale Application",
        "Repeated Security Attempts",
        "Email Changed",
        "Account Security Updated",
        "Password Updated",
        "Password Changed",
        "Email Change Requested",
        "MFA Enabled",
        "MFA Disabled",
        "Recovery Codes Replaced",
        "Administrative Access Change",
        "Deletion Request Reviewed",
        "Admin Recovery",
    ],
)
async def test_all_security_notifications_use_shared_template(provider, subject):
    async with session_scope() as db:
        queue_mail(db, "customer@example.com", subject, "Account action: approve. Reason: <Approval> & review")
        await db.commit()
    await deliver_security_mail()

    ((params, options),) = provider
    assert params["subject"] == f"Honey Summer — {subject}"
    assert "cid:honey-summer-logo" in params["html"]
    assert "&lt;Approval&gt; &amp; review" in params["html"]
    assert "With warmth, Honey Summer" in params["html"]
    assert params["attachments"]
    assert "<Approval> & review" in params["text"]
    async with session_scope() as db:
        row = await db.scalar(select(SecurityMail))
        assert options == {"idempotency_key": f"security-mail-{row.id}"}
        assert row.accepted_at and not row.encrypted_body


@pytest.mark.parametrize("path", ["/wholesale", "/admin/security/reset?kind=reset&token=secret", "/admin/login"])
async def test_security_links_remain_safe_styled_and_usable(provider, path):
    link = "https://staging.example.com" + path
    message = (
        f"Use this link within 30 minutes:\n{link}\nhttps://staging.example.com.evil.test/reset\n<script>bad</script>"
    )
    async with session_scope() as db:
        queue_mail(db, "customer@example.com", "Continue", message, challenge=True)
        await db.commit()
    await deliver_security_mail()

    params = provider[0][0]
    assert f'href="{link.replace("&", "&amp;")}"' in params["html"]
    assert "Continue securely with Honey Summer" in params["html"]
    assert "display:inline-block;padding:12px 20px" in params["html"]
    assert 'href="https://staging.example.com.evil.test' not in params["html"]
    assert "<script>" not in params["html"]
    assert "&lt;script&gt;bad&lt;/script&gt;" in params["html"]
    assert link in params["text"]
