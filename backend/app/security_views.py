"""Accessible server-rendered account, recovery, MFA and admin access workflows."""

import json as json_module
import secrets
from datetime import UTC, datetime
from urllib.parse import urlsplit

import pyotp
from itsdangerous import BadSignature, URLSafeTimedSerializer
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sanic import Blueprint
from sanic.response import html, json, redirect
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from .auth import (
    create_session_token,
    get_current_user,
    hash_password,
    session_user,
    token_digest,
    verify_password,
)
from .db import session_scope
from .models import FloristProfile, Order, User
from .security import (
    ADMIN_CSRF_COOKIE,
    SECURITY_CSRF_COOKIE,
    audit,
    consume_token,
    decrypt,
    deliver_security_mail,
    encrypt,
    issue_token,
    password_confirmation_error,
    password_error,
    public_link,
    queue_mail,
    reauth_seconds,
    recent,
    throttle,
    valid_email,
    verify_mfa,
)
from .security_models import AccountSession, PrivacyRequest, SecurityEvent, SecurityMail
from .settings import BASE_DIR, get_settings

bp = Blueprint("security", url_prefix="/admin/security")
_env = Environment(loader=FileSystemLoader(str(BASE_DIR / "templates")), autoescape=select_autoescape())
PREAUTH_COOKIE = "honeysummer_mfa_challenge"
CSRF_COOKIE = SECURITY_CSRF_COOKIE


def _challenge_serializer():
    return URLSafeTimedSerializer(get_settings().secret_key, salt="admin-mfa-challenge")


def begin_admin_mfa(user_id: int, version: int):
    """Password proof only permits MFA, not access to any admin capability."""
    response = redirect("/admin/security/mfa")
    response.add_cookie(
        PREAUTH_COOKIE,
        _challenge_serializer().dumps({"uid": user_id, "version": version}),
        max_age=300,
        httponly=True,
        secure=not get_settings().debug,
        samesite="Strict",
    )
    return response


def _preauth(request):
    try:
        return _challenge_serializer().loads(request.cookies.get(PREAUTH_COOKIE, ""), max_age=300)
    except BadSignature, KeyError, TypeError:
        return None


def _safe_reauth_next(value: str) -> str:
    """Only return a same-site admin path; never an attacker-chosen redirect target."""
    candidate = value.strip()
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/admin/"):
        return ""
    return candidate


# Security modes that belong inside the shared admin chrome when an operator is signed in.
_SHELL_MODES = {"account", "access", "privacy", "reauth", "link", "codes", "done"}


def _template_for(user, mode: str) -> str:
    """Render operator-facing security pages inside the admin shell; keep public/auth pages standalone."""
    if mode in _SHELL_MODES and user and user.role in {"admin", "staff"} and user.is_admin:
        return "admin/security_shell.html"
    return "security.html"


def _page(request, *, status=200, template="security.html", **context):
    token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
    context.setdefault("reauth_seconds", reauth_seconds(request))
    context.setdefault("reauth_csrf", token)
    context.setdefault("reauth_next", request.path)
    viewer = context.get("user")
    context.setdefault("reauth_mfa", bool(viewer and getattr(viewer, "mfa_secret", "")))
    admin_shell = template.startswith("admin/")
    if admin_shell:
        # Render inside the shared admin chrome: the catalogue nav needs the model
        # registry, and the "Users" entry should read as active on this page.
        # Imported lazily because app.admin imports this module at load time.
        from .admin import REGISTRY  # noqa: PLC0415

        context.setdefault("admin", viewer)
        context.setdefault("operator", viewer)
        context.setdefault("models", REGISTRY)
        # Account settings has no matching nav entry, so nothing is highlighted there.
        context.setdefault("active_href", "" if context.get("mode") == "account" else "/admin/security/access")
    response = html(_env.get_template(template).render(csrf_token=token, **context), status=status)
    response.add_cookie(CSRF_COOKIE, token, httponly=True, secure=not get_settings().debug, samesite="Strict")
    if admin_shell:
        # The admin shell's sign-out form is validated against this cookie.
        response.add_cookie(ADMIN_CSRF_COOKIE, token, httponly=True, secure=not get_settings().debug, samesite="Lax")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "strict-origin"
    response.headers["X-Frame-Options"] = "DENY"
    return response


async def _user(request):
    user = await session_user(request, "honeysummer_admin", "admin")
    if user and user.role in {"admin", "staff"} and user.is_admin:
        return user
    return await get_current_user(request)


async def _account_pending(uid: int) -> str:
    """Return the decrypted in-progress authenticator key, if setup has started."""
    async with session_scope() as db:
        pending = await db.scalar(select(User.mfa_pending).where(User.id == uid))
    return decrypt(pending) if pending else ""


@bp.middleware("request")
async def protect_forms(request):
    """All security forms, including login/recovery, require a cookie-bound token."""
    if request.method == "POST":
        cookie = request.cookies.get(CSRF_COOKIE, "")
        form = request.form.get("csrf_token", "")
        if not cookie or not form or not secrets.compare_digest(cookie, form):
            return json({"detail": "Invalid CSRF token. Reload the form."}, status=403)
    if request.path.rstrip("/") not in {"/admin/security/force", "/admin/security/reset", "/admin/security/recovery"}:
        user = await _user(request)
        if user and user.must_change_password:
            return redirect("/admin/security/force")


@bp.middleware("response")
async def accessible_errors(request, response):
    """Browser form errors keep a readable recovery path; API clients retain JSON."""
    if (
        response
        and response.status >= 400
        and "application/json" in (response.content_type or "")
        and "text/html" in request.headers.get("accept", "")
    ):
        detail = json_module.loads(response.body).get("detail", "Unable to save.")
        viewer = await _user(request)
        if response.status == 403 and "Recently authenticated" in detail:
            return _page(
                request,
                template=_template_for(viewer, "reauth"),
                mode="reauth",
                status=response.status,
                error=detail,
                user=viewer,
                reauth_next=_safe_reauth_next(request.path) or "/admin/security/access",
            )
        if viewer and request.path.rstrip("/") == "/admin/security/change":
            # Keep self-service form errors on the form, with the chosen action still selected.
            return _page(
                request,
                template=_template_for(viewer, "account"),
                mode="account",
                status=response.status,
                error=detail,
                user=viewer,
                selected=str(request.form.get("action", "")),
                pending=await _account_pending(viewer.id),
            )
        return _page(request, template=_template_for(viewer, "done"), mode="done", status=response.status, error=detail)


@bp.route("/mfa", methods=["GET", "POST"])
async def admin_mfa(request):
    """Step-up authenticator check for operators who have MFA enabled; opting in is optional."""
    challenge = _preauth(request)
    if not challenge:
        return redirect("/admin/login")
    uid = challenge["uid"]
    if request.method == "POST" and not await throttle(request, "mfa", str(uid)):
        return _page(request, mode="mfa", error="Please try again later.", status=429)
    async with session_scope() as db:
        user = await db.scalar(select(User).where(User.id == uid).with_for_update())
        if (
            not user
            or not user.is_active
            or user.role not in {"admin", "staff"}
            or not user.mfa_secret
            or user.security_version != challenge["version"]
        ):
            return redirect("/admin/login")
        if request.method == "POST":
            if not verify_mfa(user, str(request.form.get("code", ""))):
                audit(db, request, "mfa_login", target=uid, outcome="failed")
                await db.commit()
                return _page(request, mode="mfa", error="Invalid code.", status=400)
            audit(db, request, "mfa_login", actor=uid, target=uid)
            version = user.security_version
            await db.commit()
        else:
            return _page(request, mode="mfa")
    response = redirect("/admin/")
    response.delete_cookie(PREAUTH_COOKIE)
    response.add_cookie(
        "honeysummer_admin",
        await create_session_token(uid, "admin", expected_version=version),
        max_age=43200,
        httponly=True,
        secure=not get_settings().debug,
        samesite="Lax",
    )
    return response


@bp.route("/recovery", methods=["GET", "POST"])
async def recovery(request):
    """Same response for unknown, inactive, invited and registered addresses."""
    message = "If this address is eligible, a recovery link will be sent. Links expire after 30 minutes."
    if request.method == "GET":
        return _page(request, mode="recovery")
    email = str(request.form.get("email", "")).strip().lower()
    allowed = await throttle(request, "recovery", email, limit=5)
    async with session_scope() as db:
        user = await db.scalar(select(User).where(User.email == email)) if allowed else None
        if user and user.is_active:
            token = issue_token(db, user, "reset")
            queue_mail(
                db,
                email,
                "Reset your password",
                "Use this single-use link within 30 minutes:\n"
                + public_link(f"/admin/security/reset?token={token}&kind=reset"),
                challenge=True,
            )
            audit(db, request, "recovery_requested", target=user.id)
            await db.commit()
    # Sending is deliberately asynchronous via the outbox job, not an account-enumerating response delay.
    return _page(request, mode="recovery", message=message)


@bp.route("/reset", methods=["GET", "POST"])
async def reset(request):
    """Complete invitation/reset/email change atomically and invalidate every old session."""
    token = str(request.args.get("token", "")) if request.method == "GET" else str(request.form.get("token", ""))
    kind = str(request.args.get("kind", "reset")) if request.method == "GET" else str(request.form.get("kind", "reset"))
    if kind not in {"reset", "invite", "email"}:
        return _page(request, mode="reset", error="Invalid link.", status=400)
    if request.method == "GET":
        return _page(request, mode="reset", token=token, kind=kind)
    if not await throttle(request, "reset", limit=10):
        return _page(request, mode="reset", error="Please try again later.", status=429)
    password = str(request.form.get("password", ""))
    if kind != "email":
        error = password_error(password) or password_confirmation_error(
            password, str(request.form.get("password_confirm", ""))
        )
    else:
        error = ""
    if error:
        return _page(request, mode="reset", token=token, kind=kind, error=error, status=400)
    try:
        async with session_scope() as db:
            row = await consume_token(db, token, kind)
            if not row:
                return _page(request, mode="reset", error="Invalid, expired or already used link.", status=400)
            user = await db.scalar(select(User).where(User.id == row.user_id).with_for_update())
            if not user or user.security_version != row.version or (not user.is_active and kind != "invite"):
                return _page(request, mode="reset", error="Invalid or expired link.", status=400)
            if kind == "email":
                old_email = user.email
                user.email = row.email
                queue_mail(db, old_email, "Email changed", "Your login email has changed. Contact us if unauthorized.")
            else:
                user.password_hash = hash_password(password)
            if kind == "invite":
                user.is_active = True
            user.security_version += 1
            queue_mail(
                db,
                user.email,
                "Account security updated",
                "Your account was updated. Sign in again; old sessions are revoked.",
            )
            audit(db, request, kind + "_completed", target=user.id)
            await db.commit()
    except IntegrityError:
        return _page(request, mode="reset", error="Unable to update this account. Contact support.", status=400)
    await deliver_security_mail()
    return _page(
        request,
        mode="done",
        message="Account updated. Sign in with your new credentials. Authenticator setup is optional for operators.",
    )


@bp.route("/force", methods=["GET", "POST"])
async def force_password(request):
    """A signed-in user given a temporary password must choose a new one before continuing."""
    user = await _user(request)
    if not user:
        return redirect("/admin/login")
    if not user.must_change_password:
        return redirect("/admin/security/")
    destination = "/admin/login" if user.is_admin else "/wholesale"
    if request.method == "GET":
        return _page(request, mode="force")
    if not await throttle(request, "account_change", str(user.id)):
        return _page(request, mode="force", error="Please try again later.", status=429)
    password = str(request.form.get("password", ""))
    error = password_error(password) or password_confirmation_error(
        password, str(request.form.get("password_confirm", ""))
    )
    async with session_scope() as db:
        row = await db.scalar(select(User).where(User.id == user.id).with_for_update())
        if not row or not row.is_active or row.security_version != user.security_version:
            return redirect(destination)
        if not verify_password(row.password_hash, str(request.form.get("current_password", ""))):
            return _page(request, mode="force", error="Enter your current (temporary) password.", status=400)
        if error:
            return _page(request, mode="force", error=error, status=400)
        row.password_hash = hash_password(password)
        row.must_change_password = False
        row.security_version += 1
        queue_mail(
            db,
            row.email,
            "Password updated",
            "Your password was changed. Sign in again with your new password.",
        )
        audit(db, request, "force_password", actor=row.id, target=row.id)
        await db.commit()
    await deliver_security_mail()
    return _page(request, mode="done", message="Password updated. Sign in again with your new password.")


@bp.get("/")
async def account(request):
    """Account settings are available to pending/approved florists and operators."""
    user = await _user(request)
    if not user:
        return _page(request, mode="done", message="Sign in to manage your account.", status=401)
    return _page(
        request,
        template=_template_for(user, "account"),
        mode="account",
        user=user,
        pending=await _account_pending(user.id),
        selected=str(request.args.get("action", "")),
    )


@bp.post("/change")
async def account_change(request):
    """Validated self-service changes never allow promotion or self-approval."""
    signed_in = await _user(request)
    if not signed_in:
        return json({"detail": "Sign in first."}, status=401)
    if not await throttle(request, "account_change", str(signed_in.id)):
        return json({"detail": "Please try again later."}, status=429)
    action = str(request.form.get("action", ""))
    async with session_scope() as db:
        user = await db.scalar(select(User).options().where(User.id == signed_in.id).with_for_update())
        if not user or not user.is_active or user.security_version != signed_in.security_version:
            return json({"detail": "Sign in again."}, status=401)
        if not verify_password(user.password_hash, str(request.form.get("current_password", ""))):
            return json({"detail": "Invalid credentials."}, status=400)
        if user.mfa_secret and not verify_mfa(user, str(request.form.get("code", ""))):
            return json({"detail": "Invalid authenticator or recovery code."}, status=400)
        message = "Account updated."
        codes = []
        if action == "reauth":
            row = request.ctx.account_session
            await db.execute(
                update(AccountSession)
                .where(AccountSession.token_hash == row.token_hash)
                .values(reauthenticated_at=datetime.now(UTC))
            )
            message = "Reauthenticated for 10 minutes."
        elif action == "password":
            password = str(request.form.get("password", ""))
            error = password_error(password) or password_confirmation_error(
                password, str(request.form.get("password_confirm", ""))
            )
            if error:
                return json({"detail": error}, status=400)
            user.password_hash = hash_password(password)
            user.must_change_password = False
            user.security_version += 1
            queue_mail(
                db,
                user.email,
                "Password changed",
                "Your password changed. Sign in again; all old sessions are revoked.",
            )
        elif action == "email":
            email = str(request.form.get("email", "")).strip().lower()
            if not valid_email(email) or await db.scalar(select(User.id).where(User.email == email)):
                return json({"detail": "Unable to use this email address."}, status=400)
            token = issue_token(db, user, "email", email)
            queue_mail(
                db,
                email,
                "Confirm email change",
                "Confirm within 30 minutes:\n" + public_link(f"/admin/security/reset?kind=email&token={token}"),
                challenge=True,
            )
            queue_mail(
                db,
                user.email,
                "Email change requested",
                "A change of login email was requested. Contact us if unauthorized.",
            )
            message = "Confirm the link sent to the new address."
        elif action == "revoke":
            user.security_version += 1
            message = "All sessions revoked. Sign in again."
        elif action == "profile":
            profile = await db.scalar(select(FloristProfile).where(FloristProfile.user_id == user.id))
            if not profile:
                return json({"detail": "Florist profile required."}, status=400)
            for field, limit in (("contact_name", 200), ("business_name", 200), ("phone", 40), ("website", 500)):
                value = str(request.form.get(field, "")).strip()
                if len(value) > limit or (field in {"contact_name", "business_name"} and not value):
                    return json({"detail": "Enter valid contact and business details."}, status=400)
                if field == "website" and value and not value.startswith("https://"):
                    return json({"detail": "Use an HTTPS website URL."}, status=400)
                setattr(profile, field, value)
        elif action in {"export", "deletion"}:
            db.add(PrivacyRequest(user_id=user.id, kind=action))
            message = "Request recorded for admin review. Financial records are retained as required."
        elif action == "mfa_start":
            if user.mfa_secret:
                return json({"detail": "MFA is already enabled."}, status=400)
            user.mfa_pending = encrypt(pyotp.random_base32())
        elif action == "mfa_confirm":
            if not user.mfa_pending or user.mfa_secret:
                return json({"detail": "Start authenticator setup first."}, status=400)
            user.mfa_secret = user.mfa_pending
            if not verify_mfa(user, str(request.form.get("code", ""))):
                return json({"detail": "Invalid authenticator code."}, status=400)
            user.mfa_pending = ""
            codes = [secrets.token_hex(8) for _ in range(10)]
            user.recovery_codes = [token_digest(c) for c in codes]
            user.security_version += 1
            queue_mail(
                db, user.email, "MFA enabled", "Authenticator protection was enabled. Store recovery codes offline."
            )
        elif action == "recovery_codes":
            if not user.mfa_secret:
                return json({"detail": "Enable MFA first."}, status=400)
            codes = [secrets.token_hex(8) for _ in range(10)]
            user.recovery_codes = [token_digest(c) for c in codes]
            queue_mail(db, user.email, "Recovery codes replaced", "Old MFA recovery codes can no longer be used.")
        else:
            return json({"detail": "Unknown action."}, status=400)
        audit(db, request, action, actor=user.id, target=user.id)
        await db.commit()
    await deliver_security_mail()
    if action == "reauth":
        return redirect(_safe_reauth_next(str(request.form.get("next", ""))) or "/admin/security/")
    if codes:
        return _page(request, template=_template_for(user, "codes"), mode="codes", codes=codes)
    if action == "mfa_start":
        return redirect("/admin/security/")
    return _page(request, template=_template_for(user, "done"), mode="done", message=message)


def _row_actions(account, profile) -> list[tuple[str, str, str]]:
    """List the access actions valid for a single account row as (value, label, kind)."""
    actions: list[tuple[str, str, str]] = []
    if account.role == "florist":
        if profile and profile.application_state != "approved":
            actions.append(("approve", "Approve application", "primary"))
        if profile and profile.application_state != "denied":
            actions.append(("deny", "Deny application", "danger"))
        actions.append(
            ("suspend", "Suspend account", "danger")
            if account.is_active
            else ("reactivate", "Reactivate account", "secondary")
        )
        actions.append(("revoke", "Sign out all sessions", "quiet"))
        actions.append(("reset_mfa", "Reset authenticator", "quiet"))
    else:
        if account.role == "staff":
            actions.append(("admin", "Promote to admin", "secondary"))
            if not account.is_active:
                actions.append(("reinvite", "Reissue invitation", "secondary"))
        elif account.role == "admin":
            actions.append(("staff", "Change to staff", "quiet"))
        actions.append(
            ("suspend", "Suspend account", "danger")
            if account.is_active
            else ("reactivate", "Reactivate account", "secondary")
        )
        actions.append(("revoke", "Sign out all sessions", "quiet"))
        if account.role != "admin":
            actions.append(("reset_mfa", "Reset authenticator", "quiet"))
    if account.is_active:
        actions.append(("password", "Send password reset", "quiet"))
        actions.append(("temp_password", "Set temporary password", "quiet"))
    return actions


@bp.get("/access")
async def access(request):
    """Admin-only user table plus audit/outbox/privacy workspace with bounded filters."""
    user = await _user(request)
    if not user or user.role != "admin":
        return json({"detail": "Admin permission required."}, status=403)
    search = str(request.args.get("q", "")).strip()[:254]
    role = str(request.args.get("role", "")).strip()
    status = str(request.args.get("status", "")).strip()
    approval = str(request.args.get("approval", "")).strip()
    async with session_scope() as db:
        user_query = (
            select(User)
            .options(selectinload(User.profile))
            .outerjoin(FloristProfile, FloristProfile.user_id == User.id)
            .order_by(User.id.desc())
            .limit(200)
        )
        if search:
            user_query = user_query.where(
                or_(User.email.ilike(f"%{search}%"), FloristProfile.business_name.ilike(f"%{search}%"))
            )
        if role in {"admin", "staff", "florist"}:
            user_query = user_query.where(User.role == role)
        if status == "active":
            user_query = user_query.where(User.is_active.is_(True))
        elif status == "inactive":
            user_query = user_query.where(User.is_active.is_(False))
        if approval in {"pending", "approved", "denied"}:
            user_query = user_query.where(FloristProfile.application_state == approval)
        accounts = (await db.scalars(user_query)).all()
        rows = [
            {"user": account, "profile": account.profile, "actions": _row_actions(account, account.profile)}
            for account in accounts
        ]
        pending_count = await db.scalar(
            select(func.count()).select_from(FloristProfile).where(FloristProfile.application_state == "pending")
        )
        events_query = select(SecurityEvent).order_by(SecurityEvent.id.desc()).limit(100)
        action = str(request.args.get("action", ""))
        if action:
            events_query = events_query.where(SecurityEvent.action == action)
        events = (await db.scalars(events_query)).all()
        failures = (await db.scalars(select(SecurityMail).where(SecurityMail.accepted_at.is_(None)))).all()
        requests = (await db.scalars(select(PrivacyRequest).order_by(PrivacyRequest.id.desc()).limit(100))).all()
    return _page(
        request,
        template=_template_for(user, "access"),
        mode="access",
        user=user,
        rows=rows,
        pending_count=pending_count,
        q=search,
        role=role,
        status_filter=status,
        approval=approval,
        events=events,
        failures=failures,
        requests=requests,
    )


@bp.post("/access")
async def manage_access(request):
    """Admin-mediated lifecycle; serialized admin rows guard the last-admin invariant."""
    actor = await _user(request)
    if not actor or actor.role != "admin" or not recent(request):
        return json({"detail": "Recently authenticated admin required."}, status=403)
    if not await throttle(request, "access", str(actor.id), limit=30):
        return json({"detail": "Please try again later."}, status=429)
    action = str(request.form.get("action", ""))
    reason = str(request.form.get("reason", "")).strip()
    if not reason or len(reason) > 2000:
        return json({"detail": "A reason of up to 2000 characters is required."}, status=400)
    async with session_scope() as db:
        admins = (await db.scalars(select(User).where(User.role == "admin").order_by(User.id).with_for_update())).all()
        current_actor = next((u for u in admins if u.id == actor.id), None)
        if not current_actor or not current_actor.is_active or current_actor.security_version != actor.security_version:
            return json({"detail": "Admin session revoked. Sign in again."}, status=403)
        link = ""
        link_email = ""
        if action == "invite":
            email = str(request.form.get("email", "")).strip().lower()
            if not valid_email(email) or await db.scalar(select(User.id).where(User.email == email)):
                return json({"detail": "Unable to invite this address."}, status=400)
            user = User(
                email=email,
                password_hash=hash_password(secrets.token_urlsafe(40)),
                role="staff",
                is_admin=True,
                is_active=False,
            )
            db.add(user)
            await db.flush()
            token = issue_token(db, user, "invite")
            queue_mail(
                db,
                email,
                "Staff invitation",
                "Set up your password within 30 minutes, then sign in. Authenticator setup is optional:\n"
                + public_link(f"/admin/security/reset?kind=invite&token={token}"),
                challenge=True,
            )
        else:
            try:
                uid = int(request.form.get("user_id", "0"))
            except ValueError:
                return json({"detail": "Choose an account."}, status=400)
            user = await db.scalar(select(User).where(User.id == uid).with_for_update())
            if not user or user.id == actor.id:
                return json({"detail": "Cannot change your own access here."}, status=400)
            active_admins = [u for u in admins if u.is_active]
            if user.role == "admin" and user.is_active and len(active_admins) <= 1 and action in {"suspend", "staff"}:
                return json({"detail": "The last active admin must be retained."}, status=400)
            profile = await db.scalar(select(FloristProfile).where(FloristProfile.user_id == user.id))
            if action in {"approve", "deny"}:
                if not profile:
                    return json({"detail": "Florist application required."}, status=400)
                if profile.application_state == ("approved" if action == "approve" else "denied"):
                    return redirect("/admin/security/access")
                profile.approved = action == "approve"
                profile.application_state = "approved" if action == "approve" else "denied"
                profile.decision_reason = reason
            elif action in {"suspend", "reactivate"}:
                user.is_active = action == "reactivate"
            elif action in {"staff", "admin"}:
                if user.role == "florist":
                    return json({"detail": "Invite a separate staff account; never promote a florist."}, status=400)
                user.role = action
                user.is_admin = True
            elif action == "revoke":
                pass
            elif action == "reset_mfa":
                if user.role == "admin":
                    return json({"detail": "Admin MFA recovery requires the documented offline procedure."}, status=400)
                user.mfa_secret = user.mfa_pending = ""
                user.mfa_last_step = 0
                user.recovery_codes = []
            elif action == "reinvite":
                if user.role != "staff" or user.is_active:
                    return json({"detail": "Only inactive staff can be reinvited."}, status=400)
                user.security_version += 1
                token = issue_token(db, user, "invite")
                queue_mail(
                    db,
                    user.email,
                    "Staff invitation",
                    "Set up within 30 minutes:\n" + public_link(f"/admin/security/reset?kind=invite&token={token}"),
                    challenge=True,
                )
            elif action == "password":
                if not user.is_active:
                    return json({"detail": "Reactivate the account before sending a password reset."}, status=400)
                token = issue_token(db, user, "reset")
                link = public_link(f"/admin/security/reset?token={token}&kind=reset")
                link_email = user.email
                queue_mail(
                    db,
                    user.email,
                    "Reset your password",
                    "An administrator sent you a password reset link. Use this single-use link within 30 minutes:\n"
                    + link,
                    challenge=True,
                )
            elif action == "temp_password":
                new_password = str(request.form.get("password", ""))
                error = password_error(new_password) or password_confirmation_error(
                    new_password, str(request.form.get("password_confirm", ""))
                )
                if error:
                    return json({"detail": error}, status=400)
                user.password_hash = hash_password(new_password)
                user.must_change_password = True
                queue_mail(
                    db,
                    user.email,
                    "Temporary password set",
                    "An administrator set a temporary password for your account. Sign in with it, then choose a "
                    "new password.\n" + public_link("/admin/security/force"),
                )
            else:
                return json({"detail": "Unknown access action."}, status=400)
            if action not in {"reinvite", "password"}:
                user.security_version += 1
            queue_mail(
                db,
                user.email,
                "Account access updated",
                f"Account action: {action}. Reason: {reason}\n"
                + public_link("/wholesale" if user.role == "florist" else "/admin/login"),
            )
        queue_mail(
            db, actor.email, "Administrative access change", "An access change was recorded. Review the security audit."
        )
        audit(db, request, "access_" + action, actor=actor.id, target=user.id, reason=reason)
        await db.commit()
    await deliver_security_mail()
    if link:
        return _page(request, template=_template_for(actor, "link"), mode="link", link=link, link_email=link_email)
    return redirect("/admin/security/access")


@bp.route("/privacy/<pk:int>", methods=["GET", "POST"])
async def review_privacy(request, pk: int):
    """Admin-reviewed requests never erase financial or audit records."""
    actor = await _user(request)
    if not actor or actor.role != "admin" or (request.method == "POST" and not recent(request)):
        return json({"detail": "Recently authenticated admin required."}, status=403)
    async with session_scope() as db:
        item = await db.scalar(select(PrivacyRequest).where(PrivacyRequest.id == pk).with_for_update())
        if not item:
            return json({"detail": "Request not found."}, status=404)
        if request.method == "GET":
            return _page(request, template=_template_for(actor, "privacy"), mode="privacy", item=item)
        notes = str(request.form.get("notes", "")).strip()
        decision = str(request.form.get("decision", ""))
        if item.status != "requested" or not notes or len(notes) > 2000 or decision not in {"approve", "deny"}:
            return json({"detail": "Record an identity/retention decision for an open request."}, status=400)
        user = await db.scalar(select(User).where(User.id == item.user_id).with_for_update())
        profile = await db.scalar(select(FloristProfile).where(FloristProfile.user_id == user.id))
        if user.role != "florist":
            return json({"detail": "Operator retention requires a separate documented review."}, status=400)
        if decision == "approve" and item.kind == "export":
            orders = (await db.scalars(select(Order).where(Order.customer_id == user.id))).all()
            item.snapshot = {
                "email": user.email,
                "profile": {
                    field: getattr(profile, field)
                    for field in ("contact_name", "business_name", "phone", "website", "about_work")
                }
                if profile
                else {},
                "orders": [{"id": o.id, "status": o.status, "created_at": o.created_at.isoformat()} for o in orders],
            }
        elif decision == "approve" and item.kind == "deletion":
            # Financial contact snapshots are intentionally retained, never silently scrubbed here.
            user.is_active = False
            user.security_version += 1
            queue_mail(
                db,
                user.email,
                "Deletion request reviewed",
                "Login access is disabled and your account profile is anonymized. "
                "Legally required transaction records remain retained.",
            )
            user.email = f"deleted-{user.id}@accounts.invalid"
            user.password_hash = hash_password(secrets.token_urlsafe(40))
            user.mfa_secret = user.mfa_pending = ""
            user.recovery_codes = []
            if profile:
                profile.approved = False
                profile.business_name = "Deleted account"
                profile.contact_name = profile.phone = profile.website = profile.about_work = profile.notes = ""
        item.notes = notes
        item.status = "approved" if decision == "approve" else "denied"
        audit(db, request, "privacy_" + decision, actor=actor.id, target=user.id, reason=notes)
        await db.commit()
    await deliver_security_mail()
    return redirect(f"/admin/security/privacy/{pk}")
