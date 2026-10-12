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
from app.admin_recovery import recover
from app.auth import COOKIE_NAME, aware, create_session_token, hash_password, token_digest, verify_password
from app.db import session_scope
from app.models import FloristProfile, Order, User
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


async def admin_session(role="admin"):
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
            "password_confirm": password,
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
        data={"csrf_token": app.asgi_client.cookies.get(CSRF_COOKIE), "reason": "Verified by admin", **data},
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
            "/admin/security/reset",
            data={
                "csrf_token": csrf,
                "kind": "reset",
                "token": token,
                "password": password,
                "password_confirm": password,
            },
        )
        return response.status

    statuses = await asyncio.gather(submit("first-unique-passphrase"), submit("second-unique-passphrase"))
    assert sorted(statuses) == [200, 400]


@pytest.mark.asyncio
async def test_reset_requires_a_matching_password_confirmation():
    uid = await make_user()
    token = await token_for(uid)
    await app.asgi_client.get(f"/admin/security/reset?token={token}")
    csrf = app.asgi_client.cookies.get(CSRF_COOKIE)
    _, rejected = await app.asgi_client.post(
        "/admin/security/reset",
        data={
            "csrf_token": csrf,
            "kind": "reset",
            "token": token,
            "password": "another-unique-garden-passphrase",
            "password_confirm": "different-garden-passphrase",
        },
    )
    assert rejected.status == 400 and "did not match" in rejected.text
    # A rejected mismatch must not consume the single-use link.
    async with session_scope() as db:
        assert await db.scalar(select(AccountToken).where(AccountToken.consumed_at.is_(None))) is not None
    _, completed = await reset_token(token)
    assert completed.status == 200
    async with session_scope() as db:
        assert verify_password((await db.get(User, uid)).password_hash, "another-unique-garden-passphrase")


@pytest.mark.asyncio
async def test_account_password_change_requires_a_matching_confirmation():
    uid = await make_user()
    app.asgi_client.cookies.set(COOKIE_NAME, await create_session_token(uid))
    _, rejected = await change(
        {
            "action": "password",
            "password": "new-unique-garden-passphrase",
            "password_confirm": "different-garden-passphrase",
        }
    )
    assert rejected.status == 400 and "did not match" in rejected.json["detail"]
    async with session_scope() as db:
        assert verify_password((await db.get(User, uid)).password_hash, PASSWORD)
    _, accepted = await change(
        {
            "action": "password",
            "password": "new-unique-garden-passphrase",
            "password_confirm": "new-unique-garden-passphrase",
        }
    )
    assert accepted.status == 200
    async with session_scope() as db:
        assert verify_password((await db.get(User, uid)).password_hash, "new-unique-garden-passphrase")


@pytest.mark.asyncio
async def test_admin_temp_password_requires_a_matching_confirmation():
    await admin_session()
    target = await make_user(role="florist", email="temp-confirm@example.com")
    _, rejected = await access(
        {
            "action": "temp_password",
            "user_id": target,
            "password": "temporary-passphrase-123",
            "password_confirm": "temporary-passphrase-124",
        }
    )
    assert rejected.status == 400 and "did not match" in rejected.json["detail"]
    async with session_scope() as db:
        user = await db.get(User, target)
        assert not user.must_change_password and verify_password(user.password_hash, PASSWORD)


@pytest.mark.asyncio
async def test_force_password_requires_a_matching_confirmation():
    uid = await make_user()
    async with session_scope() as db:
        user = await db.get(User, uid)
        user.password_hash = hash_password("temporary-passphrase-123")
        user.must_change_password = True
        await db.commit()
    app.asgi_client.cookies.set(COOKIE_NAME, await create_session_token(uid))
    await app.asgi_client.get("/admin/security/force")
    _, rejected = await app.asgi_client.post(
        "/admin/security/force",
        data={
            "csrf_token": app.asgi_client.cookies.get(CSRF_COOKIE),
            "current_password": "temporary-passphrase-123",
            "password": "brand-new-passphrase-456",
            "password_confirm": "brand-new-passphrase-457",
        },
    )
    assert rejected.status == 400 and "did not match" in rejected.text
    async with session_scope() as db:
        assert (await db.get(User, uid)).must_change_password


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
    uid = await make_user(role="admin")
    await app.asgi_client.get("/admin/login")
    _, password = await app.asgi_client.post(
        "/admin/login",
        data={
            "csrf_token": app.asgi_client.cookies.get(ADMIN_CSRF_COOKIE),
            "email": "admin@example.com",
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
    uid = await make_user(role="admin", mfa=True)
    await app.asgi_client.get("/admin/login")
    _, password = await app.asgi_client.post(
        "/admin/login",
        data={
            "csrf_token": app.asgi_client.cookies.get(ADMIN_CSRF_COOKIE),
            "email": "admin@example.com",
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
    code = pyotp.TOTP(secret).now()
    _, complete = await app.asgi_client.post(
        "/admin/security/mfa",
        data={"csrf_token": app.asgi_client.cookies.get(CSRF_COOKIE), "code": code},
    )
    assert complete.status == 302 and app.asgi_client.cookies.get(ADMIN_COOKIE)
    _, dashboard = await app.asgi_client.get("/admin/")
    assert dashboard.status == 200
    async with session_scope() as db:
        assert not verify_mfa(await db.get(User, uid), code)  # No timestep replay.


@pytest.mark.asyncio
async def test_operator_can_opt_into_mfa_from_account_security():
    uid = await make_user(role="admin")
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
@pytest.mark.parametrize("role", ["admin", "staff", "florist"])
@pytest.mark.parametrize("proof", ["authenticator", "recovery"])
async def test_account_can_disable_mfa_and_revoke_all_sessions(role, proof, monkeypatch):
    uid = await make_user(role=role, mfa=True)
    recovery = "single-use-recovery-code"
    async with session_scope() as db:
        user = await db.get(User, uid)
        secret = decrypt(user.mfa_secret)
        user.mfa_pending = encrypt(pyotp.random_base32())
        user.recovery_codes = [token_digest(recovery)]
        await db.commit()
    kind = "florist" if role == "florist" else "admin"
    cookie = COOKIE_NAME if role == "florist" else ADMIN_COOKIE
    tokens = [await create_session_token(uid, kind) for _ in range(2)]
    app.asgi_client.cookies.set(cookie, tokens[0], domain="mockserver.local")
    _, page = await app.asgi_client.get("/admin/security/?action=mfa_disable")
    assert page.status == 200
    assert 'name="action" value="mfa_disable"' in page.text
    assert 'name="current_password"' in page.text and 'name="code"' in page.text
    assert "protected by your password only" in page.text
    sent = []
    monkeypatch.setattr(emails, "send_email", lambda **kwargs: sent.append(kwargs))
    code = pyotp.TOTP(secret).now() if proof == "authenticator" else recovery
    _, disabled = await change({"action": "mfa_disable", "code": code})
    assert disabled.status == 200 and "Two-step verification turned off" in disabled.text
    assert 'class="security-confirmation"' in disabled.text
    assert "What changed" in disabled.text and "Sign in again" in disabled.text
    sign_in_url = "/wholesale" if role == "florist" else "/admin/login"
    assert f'href="{sign_in_url}"' in disabled.text
    assert 'class="admin-menu"' not in disabled.text
    assert 'id="reauth-banner"' not in disabled.text
    assert not app.asgi_client.cookies.get(cookie)
    async with session_scope() as db:
        user = await db.get(User, uid)
        assert not user.mfa_secret and not user.mfa_pending and not user.recovery_codes
        assert user.mfa_last_step == 0 and user.security_version == 1
        assert not verify_mfa(user, code)
        event = await db.scalar(select(SecurityEvent).where(SecurityEvent.action == "mfa_disable"))
        assert event.actor_id == event.target_id == uid
    assert any(mail["subject"].endswith("MFA Disabled") for mail in sent)
    for token in tokens:
        app.asgi_client.cookies.set(cookie, token)
        _, blocked = await app.asgi_client.get("/admin/security/")
        assert blocked.status == 401
    app.asgi_client.cookies.clear()
    if role == "florist":
        _, login = await app.asgi_client.post(
            "/api/auth/login/", json={"email": f"{role}@example.com", "password": PASSWORD}
        )
        assert login.status == 200
    else:
        await app.asgi_client.get("/admin/login")
        _, login = await app.asgi_client.post(
            "/admin/login",
            data={
                "csrf_token": app.asgi_client.cookies.get(ADMIN_CSRF_COOKIE),
                "email": f"{role}@example.com",
                "password": PASSWORD,
            },
        )
        assert login.status == 302 and login.headers["location"].endswith("/admin/")
    _, account = await app.asgi_client.get("/admin/security/")
    assert "Two-step verification off" in account.text
    assert 'href="/admin/security/?action=mfa_disable"' not in account.text
    _, started = await change({"action": "mfa_start"})
    assert started.status == 302
    async with session_scope() as db:
        secret = decrypt((await db.get(User, uid)).mfa_pending)
    _, enrolled = await change({"action": "mfa_confirm", "code": pyotp.TOTP(secret).now()})
    assert enrolled.status == 200 and "Save your recovery codes" in enrolled.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data, status",
    [
        ({"current_password": "wrong", "code": "recovery-code"}, 400),
        ({"code": "wrong"}, 400),
        ({}, 400),
        ({"csrf_token": "wrong", "code": "recovery-code"}, 403),
    ],
)
async def test_disable_mfa_requires_password_mfa_and_csrf(data, status):
    uid = await make_user(role="admin", mfa=True)
    async with session_scope() as db:
        user = await db.get(User, uid)
        secret = user.mfa_secret
        user.recovery_codes = [token_digest("recovery-code")]
        await db.commit()
    app.asgi_client.cookies.set(ADMIN_COOKIE, await create_session_token(uid, "admin"))
    _, rejected = await change({"action": "mfa_disable", **data})
    assert rejected.status == status
    async with session_scope() as db:
        user = await db.get(User, uid)
        assert user.mfa_secret == secret and user.security_version == 0
        assert user.recovery_codes == [token_digest("recovery-code")]
        assert not await db.scalar(select(SecurityEvent).where(SecurityEvent.action == "mfa_disable"))
        assert not await db.scalar(select(SecurityMail).where(SecurityMail.subject.endswith("MFA Disabled")))


@pytest.mark.asyncio
async def test_disable_mfa_requires_signed_in_enrolled_account():
    _, anonymous = await change({"action": "mfa_disable"})
    assert anonymous.status == 401
    uid = await make_user(role="admin")
    app.asgi_client.cookies.set(ADMIN_COOKIE, await create_session_token(uid, "admin"))
    _, rejected = await change({"action": "mfa_disable"})
    assert rejected.status == 400 and "not enabled" in rejected.json["detail"]
    async with session_scope() as db:
        assert (await db.get(User, uid)).security_version == 0


@pytest.mark.asyncio
async def test_password_reset_does_not_remove_operator_mfa():
    uid = await make_user(role="admin", mfa=True)
    _, response = await reset_token(await token_for(uid))
    assert response.status == 200
    async with session_scope() as db:
        assert (await db.get(User, uid)).mfa_secret


@pytest.mark.asyncio
async def test_invite_activation_reuse_and_staff_least_privilege():
    await admin_session()
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
    _, promote = await access({"action": "admin", "user_id": uid})
    assert promote.status == 403


@pytest.mark.asyncio
async def test_users_table_lists_and_filters_accounts():
    await admin_session()
    await make_user(role="florist", email="shopper@example.com")
    _, page = await app.asgi_client.get("/admin/security/access")
    assert page.status == 200 and "shopper@example.com" in page.text and "Users" in page.text
    _, only_admin = await app.asgi_client.get("/admin/security/access?role=admin")
    assert "shopper@example.com" not in only_admin.text
    _, search = await app.asgi_client.get("/admin/security/access?q=shopper")
    assert "shopper@example.com" in search.text


@pytest.mark.asyncio
async def test_operator_security_pages_render_in_admin_shell():
    await admin_session()
    _, account = await app.asgi_client.get("/admin/security/")
    assert account.status == 200
    assert 'class="admin-menu"' in account.text
    assert "data-account-form" in account.text
    assert 'href="/admin/account" class="is-active" aria-current="page"' in account.text
    _, users = await app.asgi_client.get("/admin/security/access")
    assert 'class="admin-menu"' in users.text
    assert 'href="/admin/security/access" class="is-active" aria-current="page"' in users.text


@pytest.mark.asyncio
async def test_florist_security_page_stays_standalone():
    uid = await make_user(role="florist")
    app.asgi_client.cookies.set(COOKIE_NAME, await create_session_token(uid))
    _, page = await app.asgi_client.get("/admin/security/")
    assert page.status == 200
    assert 'class="admin-menu"' not in page.text
    assert "<h1>Account security</h1>" in page.text
    assert 'href="/wholesale"' in page.text


@pytest.mark.asyncio
async def test_admin_can_send_password_reset_link(monkeypatch):
    sent = []
    monkeypatch.setattr(emails, "send_email", lambda **kwargs: sent.append(kwargs))
    await admin_session()
    target = await make_user(role="florist", email="resetme@example.com")
    _, response = await access({"action": "password", "user_id": target})
    assert response.status == 200 and "Password reset link" in response.text
    assert any(mail["to"] == "resetme@example.com" and "Reset Your Password" in mail["subject"] for mail in sent)
    token = re.search(r"token=([^\s&\"<]+)", response.text).group(1)
    _, completed = await reset_token(token)
    assert completed.status == 200
    async with session_scope() as db:
        assert verify_password((await db.get(User, target)).password_hash, "another-unique-garden-passphrase")


@pytest.mark.asyncio
async def test_admin_temp_password_forces_change_on_next_sign_in():
    await admin_session()
    target = await make_user(role="florist", email="temp@example.com")
    _, response = await access(
        {
            "action": "temp_password",
            "user_id": target,
            "password": "temporary-passphrase-123",
            "password_confirm": "temporary-passphrase-123",
        }
    )
    assert response.status == 302
    async with session_scope() as db:
        user = await db.get(User, target)
        assert user.must_change_password and verify_password(user.password_hash, "temporary-passphrase-123")

    app.asgi_client.cookies.clear()
    app.asgi_client.cookies.set(COOKIE_NAME, await create_session_token(target))
    _, page = await app.asgi_client.get("/admin/security/force")
    assert page.status == 200 and "Choose a new password" in page.text
    _, done = await app.asgi_client.post(
        "/admin/security/force",
        data={
            "csrf_token": app.asgi_client.cookies.get(CSRF_COOKIE),
            "current_password": "temporary-passphrase-123",
            "password": "brand-new-passphrase-456",
            "password_confirm": "brand-new-passphrase-456",
        },
    )
    assert done.status == 200 and "Password updated" in done.text
    async with session_scope() as db:
        user = await db.get(User, target)
        assert not user.must_change_password and verify_password(user.password_hash, "brand-new-passphrase-456")


@pytest.mark.asyncio
async def test_admin_self_removal_forbidden_and_suspension_preserves_history():
    admin = await admin_session()
    florist = await make_user()
    cookie = await create_session_token(florist)
    async with session_scope() as db:
        db.add(Order(customer_id=florist, status="paid"))
        await db.commit()
    _, self_suspend = await access({"action": "suspend", "user_id": admin})
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
    uid = await admin_session()
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


async def _stale_admin(mfa: bool = False) -> int:
    """Create a signed-in admin whose reauthentication window has lapsed."""
    uid = await make_user(role="admin", mfa=mfa)
    app.asgi_client.cookies.set(ADMIN_COOKIE, await create_session_token(uid, "admin"))
    async with session_scope() as db:
        await db.execute(update(AccountSession).values(reauthenticated_at=datetime.now(UTC) - timedelta(minutes=11)))
        await db.commit()
    return uid


@pytest.mark.asyncio
async def test_admin_pages_show_progressive_reauth_banner():
    await admin_session()
    _, page = await app.asgi_client.get("/admin/")
    assert page.status == 200
    assert 'id="reauth-banner"' in page.text
    assert 'data-seconds="' in page.text
    assert 'action="/admin/security/change"' in page.text


@pytest.mark.asyncio
async def test_account_security_page_shows_reauth_banner_for_admins():
    await admin_session()
    _, page = await app.asgi_client.get("/admin/security/access")
    assert 'id="reauth-banner"' in page.text and 'action="/admin/security/change"' in page.text


@pytest.mark.asyncio
async def test_reauth_extends_window_and_returns_to_the_admin_page():
    await _stale_admin()
    await app.asgi_client.get("/admin/security/access")
    _, response = await app.asgi_client.post(
        "/admin/security/change",
        data={
            "csrf_token": app.asgi_client.cookies.get(CSRF_COOKIE),
            "action": "reauth",
            "next": "/admin/security/access",
            "current_password": PASSWORD,
        },
    )
    assert response.status == 302 and response.headers["location"] == "/admin/security/access"
    # The refreshed window unblocks a previously rejected sensitive change.
    _, allowed = await access({"action": "invite", "email": "rebooted@example.com"})
    assert allowed.status == 302
    async with session_scope() as db:
        row = await db.get(AccountSession, token_digest(app.asgi_client.cookies.get(ADMIN_COOKIE)))
        assert aware(row.reauthenticated_at) > datetime.now(UTC) - timedelta(minutes=10)


@pytest.mark.asyncio
async def test_reauth_ignores_offsite_redirect_targets():
    await _stale_admin()
    await app.asgi_client.get("/admin/security/")
    _, response = await app.asgi_client.post(
        "/admin/security/change",
        data={
            "csrf_token": app.asgi_client.cookies.get(CSRF_COOKIE),
            "action": "reauth",
            "next": "https://evil.example/takeover",
            "current_password": PASSWORD,
        },
    )
    assert response.status == 302 and response.headers["location"] == "/admin/security/"


@pytest.mark.asyncio
async def test_reauth_gate_renders_a_helpful_page_for_browsers():
    uid = await _stale_admin()
    await app.asgi_client.get("/admin/security/access")
    _, response = await app.asgi_client.post(
        "/admin/security/access",
        data={
            "csrf_token": app.asgi_client.cookies.get(CSRF_COOKIE),
            "user_id": uid,
            "action": "revoke",
            "reason": "Synthetic self-check",
        },
        headers={"Accept": "text/html"},
    )
    assert response.status == 403
    assert "still signed in" in response.text
    assert 'id="reauth-banner"' in response.text


@pytest.mark.asyncio
async def test_account_form_error_keeps_the_form_and_selected_action():
    uid = await make_user()
    app.asgi_client.cookies.set(COOKIE_NAME, await create_session_token(uid))
    await app.asgi_client.get("/admin/security/")
    _, response = await app.asgi_client.post(
        "/admin/security/change",
        data={
            "csrf_token": app.asgi_client.cookies.get(CSRF_COOKIE),
            "current_password": PASSWORD,
            "action": "password",
            "password": "new-unique-garden-passphrase",
            "password_confirm": "different-garden-passphrase",
        },
        headers={"Accept": "text/html"},
    )
    assert response.status == 400
    assert "did not match" in response.text
    assert "data-account-form" in response.text
    assert '<input type="hidden" name="action" value="password">' in response.text
    assert 'data-field="password"' in response.text


@pytest.mark.asyncio
async def test_account_page_defaults_florists_to_password_and_honors_action_query():
    uid = await make_user()
    app.asgi_client.cookies.set(COOKIE_NAME, await create_session_token(uid))
    _, page = await app.asgi_client.get("/admin/security/")
    assert page.status == 200
    assert '<input type="hidden" name="action" value="password">' in page.text
    assert '<select id="action"' not in page.text
    assert 'aria-label="Account security settings"' in page.text
    assert 'data-field="password"' in page.text
    _, email_page = await app.asgi_client.get("/admin/security/?action=email")
    assert '<input type="hidden" name="action" value="email">' in email_page.text
    assert 'data-field="password"' not in email_page.text
    assert 'name="email" type="email" autocomplete="email" required' in email_page.text
    app.asgi_client.cookies.clear()
    await admin_session()
    _, admin_page = await app.asgi_client.get("/admin/security/")
    assert '<input type="hidden" name="action" value="reauth">' in admin_page.text
    assert 'aria-label="Security areas"' in admin_page.text
    assert 'href="/admin/account" class="is-active" aria-current="page"' in admin_page.text
    assert 'href="/admin/security/?action=deletion"' not in admin_page.text


@pytest.mark.asyncio
async def test_account_navigation_handles_unknown_and_unavailable_actions():
    uid = await make_user(role="staff")
    app.asgi_client.cookies.set(ADMIN_COOKIE, await create_session_token(uid, "admin"))
    for action in ("unknown", "deletion", "mfa_confirm", "recovery_codes"):
        _, page = await app.asgi_client.get(f"/admin/security/?action={action}")
        assert page.status == 200
        assert '<input type="hidden" name="action" value="reauth">' in page.text
        assert 'aria-label="Security areas"' not in page.text


@pytest.mark.asyncio
async def test_account_navigation_renders_pending_setup_and_mfa_fields():
    uid = await make_user()
    app.asgi_client.cookies.set(COOKIE_NAME, await create_session_token(uid))
    _, started = await change({"action": "mfa_start"})
    assert started.status == 302
    _, setup = await app.asgi_client.get("/admin/security/")
    assert '<input type="hidden" name="action" value="mfa_confirm">' in setup.text
    assert "Authenticator setup key" in setup.text
    assert 'name="code" autocomplete="one-time-code" required' in setup.text
    async with session_scope() as db:
        user = await db.get(User, uid)
        user.mfa_secret = user.mfa_pending
        user.mfa_pending = ""
        await db.commit()
    _, enabled = await app.asgi_client.get("/admin/security/?action=recovery_codes")
    assert 'name="action" value="recovery_codes"' in enabled.text
    assert 'name="code" autocomplete="one-time-code" required' in enabled.text
    assert "Two-step verification on" in enabled.text
    assert 'href="/admin/security/?action=mfa_start"' not in enabled.text


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
    await admin_session()
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
async def test_offline_admin_recovery_requires_existing_admin_and_audits():
    uid = await make_user(role="admin", mfa=True)
    token = await create_session_token(uid, "admin")
    with pytest.raises(ValueError):
        await recover("unknown@example.com", PASSWORD, "Verified identity")
    await recover("admin@example.com", "new-unique-admin-passphrase", "Identity verified offline")
    async with session_scope() as db:
        user = await db.get(User, uid)
        assert not user.mfa_secret and user.security_version == 1
        assert await db.scalar(select(SecurityEvent).where(SecurityEvent.action == "admin_break_glass"))
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
