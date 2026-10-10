"""Security primitives: encrypted MFA, atomic throttles, audit and mail outbox."""

import asyncio
import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from html import escape
from ipaddress import ip_address, ip_network
from urllib.parse import urlsplit

import pyotp
from cryptography.fernet import Fernet
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from . import emails
from .auth import aware, token_digest
from .db import session_scope
from .models import User
from .security_models import AccountToken, SecurityEvent, SecurityMail, SecurityThrottle
from .settings import get_settings

COMMON_PASSWORDS = {"password1234", "password12345", "123456789012", "qwerty12345678"}


def password_error(password: str) -> str:
    """Permit managers/paste and long passphrases; no periodic rotation."""
    if len(password) < 12 or len(password) > 1024:
        return "Use a password of 12–1024 characters."
    if password.lower() in COMMON_PASSWORDS:
        return "Choose a less common password."
    return ""


def valid_email(email: str) -> bool:
    """Reject malformed addresses and header injection without SMTP probing."""
    return (
        3 <= len(email) <= 254
        and email.count("@") == 1
        and not any(c.isspace() for c in email)
        and "." in email.split("@")[-1]
    )


def cipher() -> Fernet:
    """Dedicated persistent key required in production; debug derives a local key."""
    settings = get_settings()
    key = settings.security_encryption_key
    if not key:
        if not settings.debug:
            raise RuntimeError("SECURITY_ENCRYPTION_KEY is required.")
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt(value: str) -> str:
    """Encrypt MFA secrets and pending security-message content."""
    return cipher().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """Decrypt only within the trusted application service."""
    return cipher().decrypt(value.encode()).decode()


def public_link(path: str) -> str:
    """Never derive security links from Host or forwarded request headers."""
    origin = get_settings().public_origin.rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.netloc
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError("PUBLIC_ORIGIN must be an absolute origin.")
    if not get_settings().debug and parsed.scheme != "https":
        raise ValueError("PUBLIC_ORIGIN requires HTTPS.")
    return origin + path


def context_hash(request) -> str:
    """Hash the first untrusted hop, never the user-selected leftmost XFF value."""
    peer = request.ip or "unknown"
    try:
        networks = [ip_network(c.strip()) for c in get_settings().trusted_proxy_cidrs.split(",") if c.strip()]
        address = ip_address(peer)
        if not any(address in n for n in networks):
            return token_digest(peer)
        chain = request.headers.get("x-forwarded-for", "").split(",")
        if len(chain) > 10:
            return token_digest(peer)
        for hop in reversed(chain):
            address = ip_address(hop.strip())
            if not any(address in n for n in networks):
                return token_digest(str(address))
    except ValueError:
        pass
    return token_digest(peer)


def audit(db, request, action: str, *, actor=None, target=None, outcome="success", reason="") -> None:
    """Append a minimal event; never include submitted secrets or raw emails."""
    db.add(
        SecurityEvent(
            actor_id=actor,
            target_id=target,
            action=action,
            outcome=outcome,
            context=context_hash(request),
            reason=reason[:2000],
        )
    )


async def throttle(request, action: str, email: str = "", *, limit: int = 10) -> bool:
    """Atomic upserts enforce IP and account counters across workers."""
    window = int(datetime.now(UTC).timestamp()) // 900
    keys = [f"{action}:ip:{context_hash(request)}:{window}"]
    if email:
        keys.append(f"{action}:account:{email}:{window}")
    allowed = True
    async with session_scope() as db:
        insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
        for raw_key in keys:
            key = token_digest(raw_key)
            stmt = insert(SecurityThrottle).values(key=key, count=1)
            count = await db.scalar(
                stmt.on_conflict_do_update(
                    index_elements=[SecurityThrottle.key], set_={"count": SecurityThrottle.count + 1}
                ).returning(SecurityThrottle.count)
            )
            allowed = allowed and count <= limit
            if count == limit + 1:
                queue_mail(
                    db,
                    get_settings().inquiry_notification_email,
                    "Repeated security attempts",
                    f"Repeated {action} attempts were throttled. Review the security audit. "
                    "No account is permanently locked.",
                )
        if not allowed:
            audit(db, request, "rate_limit", outcome="blocked")
        await db.commit()
    return allowed


def queue_mail(db, to: str, subject: str, message: str, *, challenge=False) -> None:
    """Commit notifications alongside the change; retries never log secrets."""
    body = f"Honey Summer\n\n{message}\n\nIf this wasn't you, contact {get_settings().inquiry_notification_email}.\n"
    db.add(
        SecurityMail(
            recipient=to,
            subject=f"Honey Summer — {subject}",
            encrypted_body=encrypt(body),
            expires_at=datetime.now(UTC) + timedelta(minutes=30) if challenge else None,
        )
    )


async def deliver_security_mail() -> None:
    """At-least-once outbox, with provider acceptance distinct from delivery."""
    async with session_scope() as db:
        now = datetime.now(UTC)
        await db.execute(update(SecurityMail).where(SecurityMail.expires_at <= now).values(encrypted_body=""))
        rows = (
            await db.scalars(
                select(SecurityMail)
                .where(SecurityMail.accepted_at.is_(None))
                .where(or_(SecurityMail.expires_at.is_(None), SecurityMail.expires_at > now))
                .order_by(SecurityMail.id)
                .limit(50)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for row in rows:
            row.attempts += 1
            try:
                body = decrypt(row.encrypted_body)
                if not get_settings().debug and not get_settings().resend_api_key:
                    raise RuntimeError("Production security mail requires Resend.")
                if get_settings().resend_api_key:
                    paragraphs = "".join(
                        f'<p><a href="{escape(line, quote=True)}">Continue securely with Honey Summer</a></p>'
                        if line.startswith(get_settings().public_origin.rstrip("/") + "/")
                        else f"<p>{escape(line)}</p>"
                        for line in body.split("\n")
                        if line
                    )
                    markup = (
                        '<!doctype html><html lang="en"><body style="background:#f6f2ea;color:#6a4e42;'
                        'font-family:Arial,sans-serif;line-height:1.6"><main style="max-width:600px;padding:24px">'
                        f"<h1>{escape(row.subject)}</h1>{paragraphs}</main></body></html>"
                    )
                    await asyncio.to_thread(
                        emails.send_email,
                        to=row.recipient,
                        subject=row.subject,
                        body=body,
                        html_body=markup,
                        idempotency_key=f"security-mail-{row.id}",
                    )
                else:
                    # Deliberate console-only local mail. Never include the body in exception logs.
                    emails.send_email(to=row.recipient, subject=row.subject, body=body)
                row.accepted_at = datetime.now(UTC)
                row.encrypted_body = ""
            except Exception:
                pass
        await db.commit()


def issue_token(db, user: User, kind: str, email: str = "") -> str:
    """High-entropy short-lived challenge; only its SHA-256 digest is stored."""
    token = secrets.token_urlsafe(32)
    db.add(
        AccountToken(
            token_hash=token_digest(token),
            user_id=user.id,
            kind=kind,
            email=email,
            version=user.security_version,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
    )
    return token


async def consume_token(db, token: str, kind: str):
    """Conditional update is single-use even in concurrent reset requests."""
    now = datetime.now(UTC)
    return await db.scalar(
        update(AccountToken)
        .where(
            AccountToken.token_hash == token_digest(token),
            AccountToken.kind == kind,
            AccountToken.consumed_at.is_(None),
            AccountToken.expires_at > now,
        )
        .values(consumed_at=now)
        .returning(AccountToken)
    )


def verify_mfa(user: User, code: str) -> bool:
    """Accept one TOTP timestep or one hashed recovery code, never replay."""
    if not user.mfa_secret:
        return False
    digest = token_digest(code)
    if digest in (user.recovery_codes or []):
        user.recovery_codes = [v for v in user.recovery_codes if v != digest]
        return True
    totp = pyotp.TOTP(decrypt(user.mfa_secret))
    step = int(datetime.now(UTC).timestamp()) // 30
    for candidate in (step, step - 1, step + 1):
        if candidate > user.mfa_last_step and secrets.compare_digest(totp.at(candidate * 30), code):
            user.mfa_last_step = candidate
            return True
    return False


def effective_role(user: User) -> str:
    """Legacy operators migrate to owner; is_admin never promotes a florist."""
    return user.role


def recent(request) -> bool:
    """Sensitive changes require password reauthentication (and MFA if enrolled) within 10 minutes."""
    row = getattr(request.ctx, "account_session", None)
    return bool(row and aware(row.reauthenticated_at) + timedelta(minutes=10) > datetime.now(UTC))
