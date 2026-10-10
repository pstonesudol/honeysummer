"""Adversarial account/security tests; these drive MFA without legacy test helpers."""

import asyncio
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pyotp
import pytest
from cryptography.fernet import Fernet
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import func, select, update

from app import emails
from app.admin import ADMIN_COOKIE
from app.admin import CSRF_COOKIE as ADMIN_CSRF_COOKIE
from app.auth import COOKIE_NAME, create_session_token, hash_password, token_digest, verify_password
from app.db import session_scope
from app.models import FloristProfile, Order, User
from app.owner_recovery import recover
from app.security import (
    context_hash,
    decrypt,
    deliver_security_mail,
    encrypt,
    issue_token,
    public_link,
    queue_mail,
    verify_mfa,
)
from app.security_maintenance import maintain
from app.security_models import AccountSession, AccountToken, PrivacyRequest, SecurityEvent, SecurityMail
from app.security_views import CSRF_COOKIE
from app.server import app
from app.settings import get_settings

PASSWORD = "a-unique-garden-passphrase"


@pytest.fixture(autouse=True)
def local_mail(monkeypatch):
    monkeypatch.setattr(get_settings(), "resend_api_key", "")
    monkeypatch.setattr(emails, "send_email", lambda **kwargs: None)


async def make_user(role="florist", approved=True, active=True, email=None, mfa=False):
    async with session_scope() as db:
        user = User(
            email=email or f"{role}@example.com",
            password_hash=hash_password(PASSWORD),
            role=role,
            is_admin=role != "florist",
            is_active=active,
            mfa_secret=encrypt(pyotp.random_base32()) if mfa else "",
        )
        db.add(user)
        if role == "florist":
            db.add(FloristProfile(user=user, business_name="Synthetic Studio", contact_name="June", approved=approved))
        await db.commit()
        return user.id


async def form_post(path, data=None):
    await app.asgi_client.get(path)
    return await app.asgi_client.post(
        path, data={"csrf_token": app.asgi_client.cookies.get(CSRF_COOKIE), **(data or {})}
    )


async def owner_session(role="owner"):
    uid = await make_user(role=role, mfa=True)
    app.asgi_client.cookies.set(ADMIN_COOKIE, await create_session_token(uid, "admin"))
    return uid


async def token_for(uid, kind="reset", email=""):
    async with session_scope() as db:
        user = await db.get(User, uid)
        token = issue_token(db, user, kind, email)
        await db.commit()
    return token


async def reset_token(token, kind="reset", password="another-unique-garden-passphrase"):
    await app.asgi_client.get(f"/admin/security/reset?token={token}&kind={kind}")
    return await app.asgi_client.post(
        "/admin/security/reset",
        data={
            "csrf_token": app.asgi_client.cookies.get(CSRF_COOKIE),
            "token": token,
            "kind": kind,
            "password": password,
        },
    )


async def change(data):
    await app.asgi_client.get("/admin/security/")
    return await app.asgi_client.post(
        "/admin/security/change",
        data={"csrf_token": app.asgi_client.cookies.get(CSRF_COOKIE), "current_password": PASSWORD, **data},
    )


async def access(data):
    await app.asgi_client.get("/admin/security/access")
    return await app.asgi_client.post(
        "/admin/security/access",
        data={"csrf_token": app.asgi_client.cookies.get(CSRF_COOKIE), "reason": "Verified by owner", **data},
    )


@pytest.mark.asyncio
async def test_legacy_signed_cookie_is_rejected_and_logout_revokes_copies():
    uid = await make_user()
    legacy = URLSafeTimedSerializer(get_settings().secret_key, salt="honey-summer-session").dumps({"uid": uid})
    app.asgi_client.cookies.set(COOKIE_NAME, legacy)
    _, me = await app.asgi_client.get("/api/auth/me/")
    assert not me.json["authenticated"]
    token = await create_session_token(uid)
    app.asgi_client.cookies.set(COOKIE_NAME, token)
    await app.asgi_client.post("/api/auth/logout/")
    app.asgi_client.cookies.set(COOKIE_NAME, token)
    _, after = await app.asgi_client.get("/api/auth/me/")
    assert not after.json["authenticated"]
    async with session_scope() as db:
        assert await db.get(AccountSession, token_digest(token)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["security_version", "is_active", "expires_at", "last_seen_at"])
async def test_session_invalidates_without_worker_cache(field):
    uid = await make_user()
    token = await create_session_token(uid)
    app.asgi_client.cookies.set(COOKIE_NAME, token)
    async with session_scope() as db:
        if field in {"security_version", "is_active"}:
            user = await db.get(User, uid)
            setattr(user, field, 1 if field == "security_version" else False)
        else:
            row = await db.get(AccountSession, token_digest(token))
            setattr(row, field, datetime.now(UTC) - timedelta(days=4))
        await db.commit()
    _, response = await app.asgi_client.get("/api/auth/me/")
    assert not response.json["authenticated"]


@pytest.mark.asyncio
async def test_reset_hashed_expiry_single_use_and_old_session_revocation():
    uid = await make_user()
    session = await create_session_token(uid)
    token = await token_for(uid)
    async with session_scope() as db:
        row = await db.get(AccountToken, token_digest(token))
        assert row and row.token_hash != token
    _, reset = await reset_token(token)
    assert reset.status == 200
    _, replay = await reset_token(token)
    assert replay.status == 400
    app.asgi_client.cookies.set(COOKIE_NAME, session)
    _, me = await app.asgi_client.get("/api/auth/me/")
    assert not me.json["authenticated"]
    expired = await token_for(uid)
    async with session_scope() as db:
        await db.execute(
            update(AccountToken)
            .where(AccountToken.token_hash == token_digest(expired))
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.commit()
    _, response = await reset_token(expired)
    assert response.status == 400


@pytest.mark.asyncio
async def test_reset_race_one_winner():
    uid = await make_user()
    token = await token_for(uid)
    await app.asgi_client.get(f"/admin/security/reset?token={token}")
    csrf = app.asgi_client.cookies.get(CSRF_COOKIE)

    async def submit(password):
        _, response = await app.asgi_client.post(
            "/admin/security/reset", data={"csrf_token": csrf, "kind": "reset", "token": token, "password": password}
        )
        return response.status

    statuses = await asyncio.gather(submit("first-unique-passphrase"), submit("second-unique-passphrase"))
    assert sorted(statuses) == [200, 400]


@pytest.mark.asyncio
async def test_recovery_generic_responses_throttle_and_retry_visibility(monkeypatch):
    uid = await make_user()
    _, known = await form_post("/admin/security/recovery", {"email": "florist@example.com"})
    _, unknown = await form_post("/admin/security/recovery", {"email": "unknown@example.com"})
    assert known.status == unknown.status == 200
    assert "If this address is eligible" in known.text and "If this address is eligible" in unknown.text
    async with session_scope() as db:
        row = await db.scalar(select(SecurityMail))
        assert row and "token=" not in row.encrypted_body
        assert await db.scalar(select(AccountToken.user_id)) == uid

    def fail(**kwargs):
        raise RuntimeError("Provider unavailable")

    monkeypatch.setattr(emails, "send_email", fail)
    await deliver_security_mail()
    async with session_scope() as db:
        row = await db.scalar(select(SecurityMail))
        assert row.attempts == 1 and row.accepted_at is None
    monkeypatch.setattr(emails, "send_email", lambda **kwargs: None)
    await deliver_security_mail()
    await deliver_security_mail()
    async with session_scope() as db:
        row = await db.scalar(select(SecurityMail))
        assert row.attempts == 2 and row.accepted_at and row.encrypted_body == ""


@pytest.mark.asyncio
async def test_operator_password_signs_in_when_mfa_not_enrolled():
    uid = await make_user(role="owner")
    await app.asgi_client.get("/admin/login")
    _, password = await app.asgi_client.post(
        "/admin/login",
        data={
            "csrf_token": app.asgi_client.cookies.get(ADMIN_CSRF_COOKIE),
            "email": "owner@example.com",
            "password": PASSWORD,
        },
    )
    assert password.status == 302 and password.headers["location"].endswith("/admin/")
    assert app.asgi_client.cookies.get(ADMIN_COOKIE)
    _, dashboard = await app.asgi_client.get("/admin/")
    assert dashboard.status == 200
    async with session_scope() as db:
        assert not (await db.get(User, uid)).mfa_secret


@pytest.mark.asyncio
async def test_enrolled_operator_still_requires_authenticator_after_password():
    uid = await make_user(role="owner", mfa=True)
    await app.asgi_client.get("/admin/login")
    _, password = await app.asgi_client.post(
        "/admin/login",
        data={
            "csrf_token": app.asgi_client.cookies.get(ADMIN_CSRF_COOKIE),
            "email": "owner@example.com",
            "password": PASSWORD,
        },
    )
    assert password.status == 302 and password.headers["location"].endswith("/admin/security/mfa")
    assert not app.asgi_client.cookies.get(ADMIN_COOKIE)
    _, blocked = await app.asgi_client.get("/admin/")
    assert blocked.status == 302
    await app.asgi_client.get("/admin/security/mfa")
    async with session_scope() as db:
        secret = decrypt((await db.get(User, uid)).mfa_secret)
    _, complete = await app.asgi_client.post(
        "/admin/security/mfa",
        data={"csrf_token": app.asgi_client.cookies.get(CSRF_COOKIE), "code": pyotp.TOTP(secret).now()},
    )
    assert complete.status == 302 and app.asgi_client.cookies.get(ADMIN_COOKIE)
    _, dashboard = await app.asgi_client.get("/admin/")
    assert dashboard.status == 200
    async with session_scope() as db:
        assert not verify_mfa(await db.get(User, uid), pyotp.TOTP(secret).now())  # No timestep replay.


@pytest.mark.asyncio
async def test_operator_can_opt_into_mfa_from_account_security():
    uid = await make_user(role="owner")
    app.asgi_client.cookies.set(ADMIN_COOKIE, await create_session_token(uid, "admin"))
    _, start = await change({"action": "mfa_start"})
    assert start.status == 302
    async with session_scope() as db:
        secret = decrypt((await db.get(User, uid)).mfa_pending)
    _, confirm = await change({"action": "mfa_confirm", "code": pyotp.TOTP(secret).now()})
    assert confirm.status == 200 and "Save your recovery codes" in confirm.text
    async with session_scope() as db:
        user = await db.get(User, uid)
        assert user.mfa_secret and not user.mfa_pending and len(user.recovery_codes) == 10
        codes = re.findall(r"<code>([a-f0-9]{16})</code>", confirm.text)
        assert verify_mfa(user, codes[0]) and not verify_mfa(user, codes[0])


@pytest.mark.asyncio
async def test_password_reset_does_not_remove_operator_mfa():
    uid = await make_user(role="owner", mfa=True)
    _, response = await reset_token(await token_for(uid))
    assert response.status == 200
    async with session_scope() as db:
        assert (await db.get(User, uid)).mfa_secret


@pytest.mark.asyncio
async def test_invite_activation_reuse_and_staff_least_privilege():
    await owner_session()
    _, invite = await access({"action": "invite", "email": "staff@example.com"})
    assert invite.status == 302
    # Invitation body is cleared after acceptance, so capture the independently issued challenge here.
    async with session_scope() as db:
        user = await db.scalar(select(User).where(User.email == "staff@example.com"))
        assert user.role == "staff" and not user.is_active
        uid = user.id
    token = await token_for(uid, "invite")
    _, complete = await reset_token(token, kind="invite")
    assert complete.status == 200
    _, reuse = await reset_token(token, kind="invite")
    assert reuse.status == 400
    async with session_scope() as db:
        user = await db.get(User, uid)
        assert user.is_active
        user.mfa_secret = encrypt(pyotp.random_base32())
        await db.commit()
    app.asgi_client.cookies.set(ADMIN_COOKIE, await create_session_token(uid, "admin"))
    for path in ("/admin/security/access", "/admin/reports/sales", "/admin/flowers", "/admin/orders/manual/new"):
        _, response = await app.asgi_client.get(path)
        assert response.status == 403, path
    _, orders = await app.asgi_client.get("/admin/orders")
    assert orders.status == 200
    _, promote = await access({"action": "owner", "user_id": uid})
    assert promote.status == 403


@pytest.mark.asyncio
async def test_owner_self_removal_forbidden_and_suspension_preserves_history():
    owner = await owner_session()
    florist = await make_user()
    cookie = await create_session_token(florist)
    async with session_scope() as db:
        db.add(Order(customer_id=florist, status="paid"))
        await db.commit()
    _, self_suspend = await access({"action": "suspend", "user_id": owner})
    assert self_suspend.status == 400
    _, suspend = await access({"action": "suspend", "user_id": florist})
    assert suspend.status == 302
    app.asgi_client.cookies.set(COOKIE_NAME, cookie)
    _, me = await app.asgi_client.get("/api/auth/me/")
    assert not me.json["authenticated"]
    async with session_scope() as db:
        assert await db.scalar(select(func.count()).select_from(Order)) == 1
        assert await db.scalar(select(SecurityEvent).where(SecurityEvent.action == "access_suspend"))


@pytest.mark.asyncio
async def test_email_change_confirms_new_address_then_revokes():
    uid = await make_user()
    cookie = await create_session_token(uid)
    app.asgi_client.cookies.set(COOKIE_NAME, cookie)
    sent = []
    original = emails.send_email
    emails.send_email = lambda **kwargs: sent.append(kwargs)
    try:
        _, requested = await change({"action": "email", "email": "new@example.com"})
    finally:
        emails.send_email = original
    assert requested.status == 200
    async with session_scope() as db:
        assert (await db.get(User, uid)).email == "florist@example.com"
    body = next(m["body"] for m in sent if m["to"] == "new@example.com")
    token = re.search(r"token=([\w-]+)", body).group(1)
    _, confirmed = await reset_token(token, kind="email")
    assert confirmed.status == 200
    _, me = await app.asgi_client.get("/api/auth/me/")
    assert not me.json["authenticated"]
    async with session_scope() as db:
        assert (await db.get(User, uid)).email == "new@example.com"


@pytest.mark.asyncio
async def test_csrf_origin_cors_and_secure_cookie_flags(monkeypatch):
    _, csrf = await app.asgi_client.post("/api/auth/login/", json={}, headers={"X-HoneySummer-Request": ""})
    assert csrf.status == 403
    _, cross = await app.asgi_client.post("/api/auth/login/", json={}, headers={"Origin": "https://attacker.example"})
    assert cross.status == 403 and "access-control-allow-origin" not in cross.headers
    _, form = await app.asgi_client.post("/admin/security/recovery", data={"email": "florist@example.com"})
    assert form.status == 403
    await make_user()
    monkeypatch.setattr(get_settings(), "debug", False)
    monkeypatch.setattr(get_settings(), "public_origin", "https://hellohoneysummer.com")
    _, signed = await app.asgi_client.post(
        "/api/auth/login/", json={"email": "florist@example.com", "password": PASSWORD}
    )
    assert signed.status == 200
    flags = signed.headers["set-cookie"].lower()
    assert "secure" in flags and "httponly" in flags and "samesite=lax" in flags
    assert signed.headers["cache-control"] == "no-store"
    assert signed.headers["referrer-policy"] == "strict-origin"
    with pytest.raises(ValueError):
        monkeypatch.setattr(get_settings(), "public_origin", "http://bad.example")
        public_link("/admin/security/reset")


@pytest.mark.asyncio
async def test_login_rate_limit_and_generic_failures():
    await make_user()
    for index in range(11):
        _, response = await app.asgi_client.post(
            "/api/auth/login/", json={"email": "florist@example.com", "password": "bad"}
        )
        assert response.status == (400 if index < 10 else 429)
    async with session_scope() as db:
        assert await db.scalar(select(SecurityEvent).where(SecurityEvent.action == "rate_limit"))


@pytest.mark.asyncio
async def test_recent_reauth_gate_and_session_version_race():
    uid = await owner_session()
    async with session_scope() as db:
        await db.execute(update(AccountSession).values(reauthenticated_at=datetime.now(UTC) - timedelta(minutes=11)))
        await db.commit()
    _, response = await access({"action": "invite", "email": "staff@example.com"})
    assert response.status == 403
    async with session_scope() as db:
        user = await db.get(User, uid)
        user.security_version += 1
        await db.commit()
    with pytest.raises(ValueError):
        await create_session_token(uid, "admin", expected_version=0)


@pytest.mark.asyncio
async def test_privacy_deletion_retains_financial_records():
    uid = await make_user()
    app.asgi_client.cookies.set(COOKIE_NAME, await create_session_token(uid))
    _, requested = await change({"action": "deletion"})
    assert requested.status == 200
    async with session_scope() as db:
        db.add(Order(customer_id=uid, status="paid", customer_email="financial@example.com"))
        await db.commit()
        pk = await db.scalar(select(PrivacyRequest.id))
    app.asgi_client.cookies.clear()
    await owner_session()
    _, reviewed = await form_post(
        f"/admin/security/privacy/{pk}",
        {"decision": "approve", "notes": "Identity verified; retain transaction snapshots for tax records."},
    )
    assert reviewed.status == 302
    async with session_scope() as db:
        user = await db.get(User, uid)
        assert not user.is_active and user.email.endswith("@accounts.invalid")
        assert (await db.scalar(select(Order))).customer_email == "financial@example.com"
        assert not verify_password(user.password_hash, PASSWORD)


@pytest.mark.asyncio
async def test_offline_owner_recovery_requires_existing_owner_and_audits():
    uid = await make_user(role="owner", mfa=True)
    token = await create_session_token(uid, "admin")
    with pytest.raises(ValueError):
        await recover("unknown@example.com", PASSWORD, "Verified identity")
    await recover("owner@example.com", "new-unique-owner-passphrase", "Identity verified offline")
    async with session_scope() as db:
        user = await db.get(User, uid)
        assert not user.mfa_secret and user.security_version == 1
        assert await db.scalar(select(SecurityEvent).where(SecurityEvent.action == "owner_break_glass"))
    app.asgi_client.cookies.set(ADMIN_COOKIE, token)
    _, blocked = await app.asgi_client.get("/admin/")
    assert blocked.status == 302


@pytest.mark.asyncio
async def test_expired_challenge_mail_is_redacted_and_never_sent(monkeypatch):
    uid = await make_user()
    await form_post("/admin/security/recovery", {"email": "florist@example.com"})
    async with session_scope() as db:
        await db.execute(update(SecurityMail).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        await db.commit()
    sent = []
    monkeypatch.setattr(emails, "send_email", lambda **kwargs: sent.append(kwargs))
    findings = await maintain(apply=True)
    assert not sent and findings["awaiting_acceptance"] == 1
    async with session_scope() as db:
        row = await db.scalar(select(SecurityMail))
        assert row.encrypted_body == "" and row.accepted_at is None
        assert await db.scalar(select(AccountToken.user_id)) == uid


@pytest.mark.asyncio
async def test_production_security_mail_requires_provider_and_safe_templates(monkeypatch):
    monkeypatch.setattr(get_settings(), "security_encryption_key", Fernet.generate_key().decode())
    await make_user()
    async with session_scope() as db:
        queue_mail(db, "florist@example.com", "Security <change>", "A note with <script>markup</script>.")
        await db.commit()
    monkeypatch.setattr(get_settings(), "debug", False)
    await deliver_security_mail()
    async with session_scope() as db:
        row = await db.scalar(select(SecurityMail))
        assert row.accepted_at is None and row.attempts == 1
    sent = []
    monkeypatch.setattr(get_settings(), "resend_api_key", "synthetic-mocked-provider")
    monkeypatch.setattr(emails, "send_email", lambda **kwargs: sent.append(kwargs))
    await deliver_security_mail()
    assert len(sent) == 1 and sent[0]["idempotency_key"].startswith("security-mail-")
    assert "<script>" not in sent[0]["html_body"] and "&lt;script&gt;" in sent[0]["html_body"]
    assert 'lang="en"' in sent[0]["html_body"] and sent[0]["body"]


def test_forwarded_client_ip_requires_trusted_peer_and_rightmost_chain(monkeypatch):
    request = SimpleNamespace(ip="192.0.2.12", headers={"x-forwarded-for": "1.2.3.4, 198.51.100.15"})
    monkeypatch.setattr(get_settings(), "trusted_proxy_cidrs", "")
    assert context_hash(request) == token_digest("192.0.2.12")
    monkeypatch.setattr(get_settings(), "trusted_proxy_cidrs", "192.0.2.12/32")
    assert context_hash(request) == token_digest("198.51.100.15")
    request.headers["x-forwarded-for"] = "malformed"
    assert context_hash(request) == token_digest("192.0.2.12")
