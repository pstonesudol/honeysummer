"""Accessible server-rendered account, recovery, MFA and owner access workflows."""

import json as json_module
import secrets
from datetime import UTC, datetime

import pyotp
from itsdangerous import BadSignature, URLSafeTimedSerializer
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sanic import Blueprint
from sanic.response import html, json, redirect
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

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
    audit,
    consume_token,
    decrypt,
    deliver_security_mail,
    encrypt,
    issue_token,
    password_error,
    public_link,
    queue_mail,
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
CSRF_COOKIE = "honeysummer_security_csrf"


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


def _page(request, *, status=200, **context):
    token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
    response = html(_env.get_template("security.html").render(csrf_token=token, **context), status=status)
    response.add_cookie(CSRF_COOKIE, token, httponly=True, secure=not get_settings().debug, samesite="Strict")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "strict-origin"
    response.headers["X-Frame-Options"] = "DENY"
    return response


async def _user(request):
    user = await session_user(request, "honeysummer_admin", "admin")
    if user and user.role in {"owner", "staff"} and user.is_admin and user.mfa_secret:
        return user
    return await get_current_user(request)


@bp.middleware("request")
async def protect_forms(request):
    """All security forms, including login/recovery, require a cookie-bound token."""
    if request.method == "POST":
        cookie = request.cookies.get(CSRF_COOKIE, "")
        form = request.form.get("csrf_token", "")
        if not cookie or not form or not secrets.compare_digest(cookie, form):
            return json({"detail": "Invalid CSRF token. Reload the form."}, status=403)


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
        return _page(request, mode="done", status=response.status, error=detail)


@bp.route("/mfa", methods=["GET", "POST"])
async def admin_mfa(request):
    """Mandatory operator MFA enrollment/sign-in; no admin session before proof."""
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
            or user.role not in {"owner", "staff"}
            or user.security_version != challenge["version"]
        ):
            return redirect("/admin/login")
        enrolling = not user.mfa_secret
        codes = []
        if enrolling and not user.mfa_pending:
            user.mfa_pending = encrypt(pyotp.random_base32())
            await db.commit()
        secret = decrypt(user.mfa_pending) if enrolling else ""
        uri = pyotp.TOTP(secret).provisioning_uri(user.email, issuer_name="Honey Summer") if secret else ""
        if request.method == "POST":
            if enrolling:
                user.mfa_secret = user.mfa_pending
            if not verify_mfa(user, str(request.form.get("code", ""))):
                if enrolling:
                    user.mfa_secret = ""
                audit(db, request, "mfa_login", target=uid, outcome="failed")
                await db.commit()
                return _page(request, mode="mfa", secret=secret, uri=uri, error="Invalid code.", status=400)
            if enrolling:
                user.mfa_pending = ""
                codes = [secrets.token_hex(8) for _ in range(10)]
                user.recovery_codes = [token_digest(c) for c in codes]
                user.security_version += 1
                queue_mail(
                    db, user.email, "MFA enabled", "Authenticator protection is enabled. Store recovery codes offline."
                )
            audit(db, request, "mfa_login", actor=uid, target=uid)
            version = user.security_version
            await db.commit()
        else:
            return _page(request, mode="mfa", secret=secret, uri=uri)
    response = _page(request, mode="codes", codes=codes) if codes else redirect("/admin/")
    response.delete_cookie(PREAUTH_COOKIE)
    response.add_cookie(
        "honeysummer_admin",
        await create_session_token(uid, "admin", expected_version=version),
        max_age=43200,
        httponly=True,
        secure=not get_settings().debug,
        samesite="Lax",
    )
    await deliver_security_mail()
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
    error = password_error(password) if kind != "email" else ""
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
        message="Account updated. Sign in with your new credentials. MFA is still required for operators.",
    )


@bp.get("/")
async def account(request):
    """Account settings are available to pending/approved florists and operators."""
    user = await _user(request)
    if not user:
        return _page(request, mode="done", message="Sign in to manage your account.", status=401)
    async with session_scope() as db:
        pending = await db.scalar(select(User.mfa_pending).where(User.id == user.id))
    return _page(request, mode="account", user=user, pending=decrypt(pending) if pending else "")


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
            if password_error(password):
                return json({"detail": password_error(password)}, status=400)
            user.password_hash = hash_password(password)
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
            message = "Request recorded for owner review. Financial records are retained as required."
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
    if codes:
        return _page(request, mode="codes", codes=codes)
    if action == "mfa_start":
        return redirect("/admin/security/")
    return _page(request, mode="done", message=message)


@bp.get("/access")
async def access(request):
    """Owner-only account/audit/outbox/privacy workspace with bounded filters."""
    user = await _user(request)
    if not user or user.role != "owner":
        return json({"detail": "Owner permission required."}, status=403)
    async with session_scope() as db:
        user_query = select(User).order_by(User.id.desc()).limit(200)
        search = str(request.args.get("q", "")).strip()[:254]
        if search:
            user_query = user_query.where(User.email.ilike(f"%{search}%"))
        users = (await db.scalars(user_query)).all()
        events_query = select(SecurityEvent).order_by(SecurityEvent.id.desc()).limit(100)
        action = str(request.args.get("action", ""))
        if action:
            events_query = events_query.where(SecurityEvent.action == action)
        events = (await db.scalars(events_query)).all()
        failures = (await db.scalars(select(SecurityMail).where(SecurityMail.accepted_at.is_(None)))).all()
        requests = (await db.scalars(select(PrivacyRequest).order_by(PrivacyRequest.id.desc()).limit(100))).all()
    return _page(request, mode="access", user=user, users=users, events=events, failures=failures, requests=requests)


@bp.post("/access")
async def manage_access(request):
    """Owner-mediated lifecycle; serialized owner rows guard the last-owner invariant."""
    actor = await _user(request)
    if not actor or actor.role != "owner" or not recent(request):
        return json({"detail": "Recently authenticated owner required."}, status=403)
    if not await throttle(request, "access", str(actor.id), limit=30):
        return json({"detail": "Please try again later."}, status=429)
    action = str(request.form.get("action", ""))
    reason = str(request.form.get("reason", "")).strip()
    if not reason or len(reason) > 2000:
        return json({"detail": "A reason of up to 2000 characters is required."}, status=400)
    async with session_scope() as db:
        owners = (await db.scalars(select(User).where(User.role == "owner").order_by(User.id).with_for_update())).all()
        current_actor = next((u for u in owners if u.id == actor.id), None)
        if not current_actor or not current_actor.is_active or current_actor.security_version != actor.security_version:
            return json({"detail": "Owner session revoked. Sign in again."}, status=403)
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
                "Set up your password within 30 minutes, then enroll MFA:\n"
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
            active_owners = [u for u in owners if u.is_active]
            if user.role == "owner" and user.is_active and len(active_owners) <= 1 and action in {"suspend", "staff"}:
                return json({"detail": "The last active owner must be retained."}, status=400)
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
            elif action in {"staff", "owner"}:
                if user.role == "florist":
                    return json({"detail": "Invite a separate staff account; never promote a florist."}, status=400)
                user.role = action
                user.is_admin = True
            elif action == "revoke":
                pass
            elif action == "reset_mfa":
                if user.role == "owner":
                    return json({"detail": "Owner MFA recovery requires the documented offline procedure."}, status=400)
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
            else:
                return json({"detail": "Unknown access action."}, status=400)
            if action != "reinvite":
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
    return redirect("/admin/security/access")


@bp.route("/privacy/<pk:int>", methods=["GET", "POST"])
async def review_privacy(request, pk: int):
    """Owner-reviewed requests never erase financial or audit records."""
    actor = await _user(request)
    if not actor or actor.role != "owner" or (request.method == "POST" and not recent(request)):
        return json({"detail": "Recently authenticated owner required."}, status=403)
    async with session_scope() as db:
        item = await db.scalar(select(PrivacyRequest).where(PrivacyRequest.id == pk).with_for_update())
        if not item:
            return json({"detail": "Request not found."}, status=404)
        if request.method == "GET":
            return _page(request, mode="privacy", item=item)
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
