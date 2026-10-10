"""Operator admin for Honey Summer, served by the same Sanic process at /admin.

A compact, purpose-built replacement for Django admin: signed-cookie login for
``is_admin`` users, CSRF-protected forms, and generic list/edit views driven by
a small per-model registry.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json as json_module
import re
import secrets
import uuid
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sanic import Blueprint
from sanic.response import html, json, raw, redirect, text
from sqlalchemy import func, or_, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from .auth import create_session_token, revoke_session, session_user, verify_login_password
from .balance_report import invoice_balance_rows
from .correspondence import parse_email
from .db import session_scope
from .emails import send_wholesale_approval_email
from .form_errors import FieldValidationError
from .invoice_refunds import (
    close_fully_refunded_quote,
    import_external_invoice_refund,
    issue_invoice_refund,
    reconcile_invoice_refund,
)
from .manual_orders import _money, create_manual_order
from .media import public_media_url, read_private_image, store_image
from .models import (
    AdminActivity,
    Announcement,
    BouquetProposal,
    FloristProfile,
    FlowerListing,
    GalleryImage,
    Inquiry,
    InquiryCorrespondence,
    InventoryMovement,
    InvoiceRefund,
    Order,
    OrderItem,
    OrderNotification,
    OrderRefund,
    ReconciliationRun,
    SiteContent,
    User,
    WeddingInvoice,
    WeddingQuote,
)
from .operations_report import operations_rows
from .orders import StockError, change_stock, load_order, release_order
from .payments import deliver_notifications, expire_checkout
from .proposals import send_invoice, update_sent_invoice, validate_draft
from .refunds import issue_refund
from .security import audit, recent, throttle
from .security_views import begin_admin_mfa
from .settings import BASE_DIR, get_settings
from .site_content import PHOTO_SLOTS, validate_content
from .weddings import (
    agree_revised_wedding,
    approve_wedding_schedule,
    attach_reviewed_wedding_invoice,
    next_installment_index,
    reconcile_wedding_invoice,
    revise_wedding_invoice,
    send_wedding_invoice,
    validate_installments,
    validate_quote,
    validate_schedule,
)

bp = Blueprint("admin", url_prefix="/admin")

ADMIN_COOKIE = "honeysummer_admin"
CSRF_COOKIE = "honeysummer_csrf"
ADMIN_SESSION_MAX_AGE = 60 * 60 * 12  # 12 hours

_env = Environment(
    loader=FileSystemLoader(str(BASE_DIR / "templates")),
    autoescape=select_autoescape(["html"]),
)


def _admin_label(value) -> str:
    """Human-readable display only; form/API values stay unchanged."""
    if value is None or value == "":
        return "—"
    key = str(value)
    if match := re.fullmatch(r"part_(\d+)", key):
        return f"Installment {int(match.group(1))}"
    labels = {
        "full": "Full upfront",
        "deposit": "Deposit",
        "balance": "Balance",
        "installments": "Installments",
        "deposit_paid": "Deposit paid · balance due",
        "installment_paid": "Installment paid · balance due",
        "balance_sent": "Balance invoice sent",
        "installment_sent": "Installment invoice sent",
        "amended": "Revised balance",
        "amendment_ready": "Revised balance ready",
        "amendment_sent": "Revised balance sent",
        "sent": "Invoice sent",
        "issuing": "Sending invoice",
        "review": "Needs review",
        "scheduled": "Scheduled",
        "void": "Voided",
        "stripe_invoice": "Stripe invoice",
        "external": "External payment",
        "market_sale": "Market sale",
    }
    return labels.get(key, key.replace("_", " ").capitalize())


def _admin_date(value) -> str:
    """Render stored dates in a readable form, converting timestamps to Eastern."""
    if value is None or value == "":
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value) if "T" in value else date.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(ZoneInfo("America/New_York"))
        return f"{value.strftime('%b')} {value.day}, {value.year} · {value.strftime('%I:%M %p %Z').lstrip('0')}".strip()
    if isinstance(value, date):
        return f"{value.strftime('%b')} {value.day}, {value.year}"
    return str(value)


def _admin_tone(value) -> str:
    if value in ("paid", "completed", "approved"):
        return "success"
    if value in ("review", "stock_review", "void", "refunded", "payment_failed"):
        return "attention"
    return "neutral"


_env.filters["admin_label"] = _admin_label
_env.filters["admin_date"] = _admin_date
_env.filters["admin_tone"] = _admin_tone


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
@dataclass
class Field:
    """One editable or readonly control in an admin form."""

    name: str
    label: str
    kind: str = "text"  # text | textarea | int | decimal | bool | select | file | readonly
    choices: tuple = ()
    readonly: bool = False


@dataclass
class ModelAdmin:
    """Registry entry describing the list, edit and actions for a model."""

    slug: str
    label: str
    model: Any
    fields: list[Field]
    list_columns: list[tuple[str, str]]
    order_by: list[str] = dataclass_field(default_factory=lambda: ["id"])
    search: tuple = ()
    can_create: bool = True
    actions: tuple = ()
    subdir: str = ""
    # Extra relationship paths to eager-load (beyond those already referenced
    # by list columns and editable fields), so computed properties that touch
    # related objects never trigger a lazy load outside the session.
    eager: tuple = ()


def _str_field(name: str, label: str, **kwargs) -> Field:
    return Field(name, label, "text", **kwargs)


REGISTRY: list[ModelAdmin] = [
    ModelAdmin(
        slug="announcements",
        label="Announcements",
        model=Announcement,
        fields=[
            _str_field("text", "Text"),
            _str_field("link_url", "Link URL"),
            _str_field("link_label", "Link label"),
            Field("active", "Active", "bool"),
            Field("starts_on", "Show from (Eastern, optional)", "date"),
            Field("ends_on", "Show through (Eastern, optional)", "date"),
        ],
        list_columns=[("Text", "text"), ("Active", "active"), ("Link label", "link_label")],
        order_by=["-created_at"],
        search=("text",),
    ),
    ModelAdmin(
        slug="gallery",
        label="Gallery",
        model=GalleryImage,
        fields=[
            Field("image", "Image", "file"),
            _str_field("alt_text", "Alt text"),
            _str_field("caption", "Caption"),
            Field("sort_order", "Sort order", "int"),
            Field("focal_x", "Focal point X % (0–100)", "int"),
            Field("focal_y", "Focal point Y % (0–100)", "int"),
            Field("active", "Active", "bool"),
        ],
        list_columns=[("Image", "image"), ("Caption", "caption"), ("Sort", "sort_order"), ("Active", "active")],
        order_by=["sort_order", "id"],
        search=("caption", "alt_text"),
        subdir="gallery",
    ),
    ModelAdmin(
        slug="flowers",
        label="Flower listings",
        model=FlowerListing,
        fields=[
            _str_field("name", "Name"),
            _str_field("variety", "Variety"),
            _str_field("color", "Color"),
            Field("photo", "Photo", "file"),
            _str_field("stem_notes", "Stem notes"),
            Field("price", "Price", "decimal"),
            Field("delivery_fee", "Delivery fee ($; delivery only)", "decimal"),
            Field(
                "delivery_fee_mode",
                "Delivery fee frequency",
                "select",
                choices=(
                    ("per_listing", "Once per listing"),
                    ("per_unit", "Per unit"),
                    ("per_order", "Once per order (highest fee wins)"),
                ),
            ),
            Field("unit", "Unit", "select", choices=(("stem", "Per stem"), ("bunch", "Per bunch"))),
            Field("quantity_available", "Quantity available", "int"),
            Field("sold_out", "Sold out", "bool"),
            Field(
                "channel",
                "Channel",
                "select",
                choices=(("retail", "Retail"), ("wholesale", "Wholesale"), ("both", "Both")),
            ),
            Field(
                "season",
                "Season",
                "select",
                choices=(
                    ("", "Not assigned"),
                    ("spring", "Spring"),
                    ("summer", "Summer"),
                    ("fall", "Fall"),
                    ("winter", "Winter"),
                    ("year_round", "Year-round"),
                ),
            ),
            Field("active", "Active", "bool"),
            Field("sort_order", "Sort order", "int"),
            Field("low_stock_threshold", "Low stock alert at or below", "int"),
        ],
        list_columns=[
            ("Code", "listing_code"),
            ("Name", "name"),
            ("Variety", "variety"),
            ("Channel", "channel"),
            ("Season", "season"),
            ("Price", "price"),
            ("Qty", "quantity_available"),
            ("Low at", "low_stock_threshold"),
            ("Sold out", "sold_out"),
            ("Active", "active"),
        ],
        order_by=["sort_order", "name", "id"],
        search=("name", "variety", "color"),
        subdir="flowers",
    ),
    ModelAdmin(
        slug="florists",
        label="Florist accounts",
        model=FloristProfile,
        fields=[
            Field("user", "User", "readonly"),
            Field("contact_name", "Contact name", "readonly"),
            _str_field("business_name", "Business name"),
            _str_field("phone", "Phone"),
            Field("business_type", "Business type", "readonly"),
            Field("website", "Website or Instagram", "readonly"),
            Field("about_work", "About their work", "readonly"),
            Field("approved", "Approved (manage in Account security)", "readonly"),
            Field("notes", "Notes", "textarea"),
        ],
        list_columns=[
            ("Business", "business_name"),
            ("User", "user"),
            ("Approved", "approved"),
            ("Phone", "phone"),
        ],
        order_by=["business_name"],
        search=("business_name", "contact_name"),
        can_create=False,
        actions=(),
    ),
    ModelAdmin(
        slug="inquiries",
        label="Inquiries",
        model=Inquiry,
        fields=[
            Field("kind", "Kind", "readonly"),
            Field("name", "Name", "readonly"),
            Field("email", "Email", "readonly"),
            Field("phone", "Phone", "readonly"),
            Field("message", "Message", "readonly"),
            Field("details", "Details", "readonly"),
            Field("photo", "Photo", "readonly"),
            Field("handled", "Handled", "readonly"),
            Field("stage", "Stage", "readonly"),
            Field("follow_up_date", "Follow up", "readonly"),
            Field("internal_notes", "Internal notes", "readonly"),
        ],
        list_columns=[
            ("Kind", "kind"),
            ("Name", "name"),
            ("Email", "email"),
            ("Handled", "handled"),
            ("Stage", "stage"),
            ("Follow up", "follow_up_date"),
            ("Received", "created_at"),
        ],
        order_by=["-created_at"],
        search=("name", "email", "message"),
        can_create=False,
    ),
    ModelAdmin(
        slug="orders",
        label="Orders",
        model=Order,
        fields=[
            Field("id", "Order", "readonly"),
            Field("order_reference", "Order reference", "readonly"),
            Field("customer_label", "Customer", "readonly"),
            Field("channel", "Channel", "readonly"),
            Field(
                "status",
                "Status",
                "readonly",
            ),
            Field("fulfilled_at", "Fulfilled at", "readonly"),
            Field("restocked_at", "Restocked at", "readonly"),
            Field("fulfillment", "Fulfillment", "readonly"),
            Field("delivery_fee", "Delivery fee", "readonly"),
            Field("pickup_window", "Pickup window", "readonly"),
            Field("delivery_address", "Delivery address", "readonly"),
            Field("notes", "Notes", "readonly"),
            Field("fulfillment_date", "Scheduled date", "readonly"),
            Field("fulfillment_time", "Scheduled time", "readonly"),
            Field("fulfillment_state", "Preparation", "readonly"),
            Field("stripe_session_id", "Stripe session", "readonly"),
        ],
        list_columns=[
            ("Order", "order_reference"),
            ("Customer", "customer_label"),
            ("Channel", "channel"),
            ("Status", "status"),
            ("Fulfillment", "fulfillment"),
            ("Scheduled", "fulfillment_date"),
            ("Preparation", "fulfillment_state"),
            ("Placed", "created_at"),
        ],
        order_by=["-created_at"],
        search=("customer_name", "customer_email", "stripe_session_id"),
        can_create=False,
        actions=("cancel", "fulfill", "restock"),
        eager=("customer", "customer.profile"),
    ),
]

REGISTRY_BY_SLUG = {admin.slug: admin for admin in REGISTRY}

_NAV_HREFS = (
    "/admin/",
    "/admin/proposals/",
    "/admin/weddings/",
    "/admin/inventory/stock",
    "/admin/orders/preparation",
    "/admin/reports/sales",
    "/admin/reports/balances",
    "/admin/reports/operations",
    "/admin/operations/attention",
    "/admin/site-content",
    "/admin/customers",
    "/admin/activity",
    "/admin/account",
) + tuple(f"/admin/{entry.slug}" for entry in REGISTRY)


def _active_href(path: str) -> str:
    """Return the most specific admin navigation href for the current request path."""
    path = path.split("?", 1)[0].rstrip("/")
    best = ""
    for href in _NAV_HREFS:
        base = href.rstrip("/")
        if (path == base or path.startswith(base + "/")) and len(base) > len(best.rstrip("/")):
            best = href
    return best


# --------------------------------------------------------------------------- #
# Session + CSRF
# --------------------------------------------------------------------------- #
async def get_current_admin(request) -> User | None:
    """Load the signed-in operator from the request, if any."""
    user = await session_user(request, ADMIN_COOKIE, "admin")
    return user if user and user.is_admin and user.role in {"owner", "staff"} else None


def _valid_csrf(request) -> bool:
    form_token = request.form.get("csrf_token")
    cookie_token = request.cookies.get(CSRF_COOKIE)
    if not form_token or not cookie_token:
        return False
    return secrets.compare_digest(form_token, cookie_token)


@bp.middleware("request")
async def load_admin(request):
    """Load the current operator into the request context."""
    request.ctx.admin = await get_current_admin(request)
    user = request.ctx.admin
    if user and user.role == "staff":
        # Staff may fulfill orders/read preparation only, never finance, PII exports or access administration.
        path = request.path.rstrip("/")
        if path == "/admin":
            return redirect("/admin/orders")
        allowed = path in {"/admin/account", "/admin/logout", "/admin/orders/preparation", "/admin/orders"}
        if request.method == "GET" and re.fullmatch(r"/admin/orders/\d+(/packing-slip)?", path):
            allowed = True
        if request.method == "POST" and re.fullmatch(r"/admin/orders/\d+/fulfillment", path):
            allowed = True
        if not allowed:
            return json({"detail": "Owner permission required."}, status=403)
    if user and request.method == "POST" and request.path not in {"/admin/logout", "/admin/login"}:
        if not recent(request):
            return json({"detail": "Reauthenticate in Account security before making changes."}, status=403)


@bp.middleware("response")
async def show_form_error(request, response):
    """Keep browser form failures in the admin, while preserving JSON for API clients."""
    if (
        request.method != "POST"
        or not response
        or response.status < 400
        or "text/html" not in request.headers.get("accept", "")
        or "application/json" not in (response.content_type or "")
    ):
        return
    try:
        message = json_module.loads(response.body).get("detail")
    except ValueError, TypeError, AttributeError:
        return
    if isinstance(message, str):
        return _page(request, "admin/error.html", status=response.status, error=message)


@bp.middleware("response")
async def record_admin_outcome(request, response):
    """Record POST outcomes, not passwords, uploaded content or customer form values."""
    actor = getattr(request.ctx, "admin", None)
    if request.method == "POST" and actor and response:
        async with session_scope() as db:
            db.add(AdminActivity(actor_id=actor.id, path=request.path[:500], status_code=response.status))
            await db.commit()


@bp.get("/account")
async def account_settings(request):
    """Show account details without exposing or changing access credentials."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    return _page(request, "admin/account.html", account=request.ctx.admin)


@bp.get("/orders/preparation")
async def daily_preparation(request):
    """Print paid-order preparation quantities for one Eastern fulfillment day."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    try:
        day = date.fromisoformat(str(request.args.get("date", datetime.now(ZoneInfo("America/New_York")).date())))
    except ValueError:
        return json({"detail": "Choose a valid preparation date."}, status=400)
    async with session_scope() as db:
        orders = (
            await db.scalars(
                select(Order)
                .options(selectinload(Order.items))
                .where(Order.status == "paid", Order.fulfillment_date == day, Order.fulfillment_state != "completed")
                .order_by(Order.fulfillment_time, Order.id)
            )
        ).all()
    quantities = {}
    for order in orders:
        for item in order.items:
            key = (item.listing_id, item.name_snapshot)
            quantities[key] = quantities.get(key, 0) + item.quantity
    return _page(
        request,
        "admin/preparation.html",
        day=day,
        orders=orders,
        quantities=sorted(quantities.items(), key=lambda row: row[0][1].lower()),
    )


@bp.get("/activity")
async def administrative_activity(request):
    """Show filtered, paginated administrative request outcomes."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    async with session_scope() as db:
        query = select(AdminActivity, User.email).join(User, User.id == AdminActivity.actor_id)
        path = str(request.args.get("path", "")).strip()[:100]
        if path:
            query = query.where(AdminActivity.path.contains(path, autoescape=True))
        rows = (await db.execute(query.order_by(AdminActivity.id.desc()).offset((page - 1) * 50).limit(51))).all()
    return _page(request, "admin/activity.html", rows=rows[:50], more=len(rows) > 50, page=page, path=path)


def _page(request, template: str, status: int = 200, **context):
    token = secrets.token_urlsafe(32)
    context.setdefault("csrf_token", token)
    context.setdefault("admin", request.ctx.admin)
    context.setdefault("operator", request.ctx.admin)
    context.setdefault("models", REGISTRY)
    context.setdefault("active_href", _active_href(request.path))
    context.setdefault("media_url", public_media_url())
    response = html(_env.get_template(template).render(**context), status=status)
    response.add_cookie(
        CSRF_COOKIE,
        token,
        httponly=True,
        samesite="Lax",
        secure=not get_settings().debug,
    )
    return response


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _order_columns(model, names: list[str]) -> list:
    columns = []
    for name in names:
        descending = name.startswith("-")
        attribute = getattr(model, name.lstrip("-"))
        columns.append(attribute.desc() if descending else attribute)
    return columns


def _relationship_options(model, paths) -> list:
    """Eager-load relationships referenced by display/edit paths.

    Reading an unloaded relationship outside an async session raises
    MissingGreenlet, so anything the admin renders must be pre-loaded. Paths
    may nest (``customer.profile``) to load a chain.
    """
    tree: dict = {}
    for path in paths:
        parts = path.split(".")
        current = model
        node = tree
        for part in parts:
            if part not in sa_inspect(current).relationships:
                break
            node = node.setdefault(part, {})
            current = sa_inspect(current).relationships[part].mapper.class_

    def build(mapper_class, subtree):
        options = []
        for name, child in subtree.items():
            loader = selectinload(getattr(mapper_class, name))
            if child:
                nested = build(sa_inspect(mapper_class).relationships[name].mapper.class_, child)
                loader = loader.options(*nested)
            options.append(loader)
        return options

    return build(model, tree)


def _display_value(obj, path: str) -> str:
    value: Any = obj
    for part in path.split("."):
        value = getattr(value, part, "")
    if path in ("status", "channel", "fulfillment", "fulfillment_state", "stage", "kind"):
        return _admin_label(value)
    if path in ("created_at", "fulfillment_date", "follow_up_date"):
        return _admin_date(value)
    return "" if value is None else str(value)


def _field_row(obj, field: Field) -> dict:
    value = getattr(obj, field.name, "") if obj is not None else ""
    input_type = "text"
    step = None
    if field.kind == "int":
        input_type = "number"
    elif field.kind == "decimal":
        input_type = "number"
        step = "0.01"
    elif field.kind == "date":
        input_type = "date"
    return {"field": field, "value": value, "input_type": input_type, "step": step}


async def _apply_form(obj, admin: ModelAdmin, form, files) -> None:
    for field in admin.fields:
        if field.readonly:
            continue
        if admin.slug == "flowers" and field.name == "quantity_available" and obj.id is not None:
            continue
        if field.kind == "file":
            upload = files.get(field.name)
            if upload and upload.name:
                setattr(obj, field.name, await asyncio.to_thread(store_image, upload, admin.subdir or "uploads"))
            continue
        raw = form.get(field.name)
        if field.kind == "bool":
            setattr(obj, field.name, raw in ("on", "true", "1"))
        elif field.kind == "date":
            try:
                setattr(obj, field.name, date.fromisoformat(raw) if raw else None)
            except ValueError:
                raise ValueError(f"Enter a valid {field.label.lower()} date.") from None
        elif field.kind == "int":
            try:
                setattr(obj, field.name, int(raw or 0))
            except TypeError, ValueError:
                pass
        elif field.kind == "decimal":
            try:
                setattr(obj, field.name, Decimal(str(raw or 0)))
            except InvalidOperation:
                pass
        elif isinstance(raw, str):
            setattr(obj, field.name, raw.strip())
        elif raw is not None:
            setattr(obj, field.name, raw)


def _flower_delivery_fee_error(form) -> str | None:
    if form.get("season", "") not in ("", "spring", "summer", "fall", "winter", "year_round"):
        return "Choose a valid season."
    raw = form.get("delivery_fee")
    if raw is not None:
        try:
            fee = Decimal(str(raw or 0))
        except InvalidOperation:
            return "Enter a valid delivery fee."
        if not fee.is_finite() or fee < 0 or fee > Decimal("999999.99"):
            return "Delivery fee must be between $0 and $999999.99."
    mode = form.get("delivery_fee_mode")
    if mode is not None and mode not in ("per_listing", "per_unit", "per_order"):
        return "Choose a valid delivery fee frequency."
    threshold = form.get("low_stock_threshold")
    if threshold is not None:
        try:
            if not 0 <= int(threshold) <= 999999:
                raise ValueError
        except ValueError, TypeError:
            return "Low stock threshold must be a nonnegative whole number."
    return None


def _announcement_error(form) -> str | None:

    link = str(form.get("link_url", "")).strip()
    if link:
        parsed = urlsplit(link)
        if not (
            (parsed.scheme in ("http", "https") and parsed.netloc)
            or (link.startswith("/") and not link.startswith("//") and not parsed.scheme)
        ):
            return "Use a valid http(s) or site-relative announcement link."
    try:
        first = date.fromisoformat(str(form.get("starts_on"))) if form.get("starts_on") else None
        last = date.fromisoformat(str(form.get("ends_on"))) if form.get("ends_on") else None
    except ValueError:
        return "Use valid YYYY-MM-DD announcement dates."
    if first and last and last < first:
        return "Announcement end date must be on or after its start date."
    return None


def _gallery_error(form) -> str | None:
    if not str(form.get("alt_text", "")).strip():
        return "Give this image descriptive alt text."
    for field in ("focal_x", "focal_y"):
        try:
            value = int(str(form.get(field, "50")))
        except ValueError:
            return "Focal point coordinates must be whole numbers from 0 to 100."
        if not 0 <= value <= 100:
            return "Focal point coordinates must be from 0 to 100."
    return None


async def _selected_gallery_image(db, form, files, slug):
    raw = str(form.get("gallery_image_id", "")).strip()
    if slug != "flowers" or not raw:
        return None
    upload = files.get("photo")
    if upload and upload.name:
        raise ValueError("Choose an existing gallery photo or upload a new one, not both.")
    try:
        image_id = int(raw)
    except ValueError:
        raise ValueError("Choose a valid gallery image.") from None
    image = await db.get(GalleryImage, image_id)
    if not image or not image.image:
        raise ValueError("That gallery image no longer exists.")
    return image


# --------------------------------------------------------------------------- #
# Auth views
# --------------------------------------------------------------------------- #
@bp.get("/login")
async def login_page(request):
    """Render the admin sign-in page, or redirect a signed-in operator."""
    if request.ctx.admin:
        return redirect("/admin/")
    return _page(request, "admin/login.html", error=None)


@bp.post("/login")
async def login_submit(request):
    """Validate operator credentials and set the signed admin cookie."""
    if not _valid_csrf(request):
        return _page(request, "admin/login.html", status=403, error="Your session expired. Please try again.")
    email = str(request.form.get("email", "")).strip().lower()
    password = str(request.form.get("password", ""))
    if not await throttle(request, "admin_login", email):
        return _page(request, "admin/login.html", status=429, error="Please try again later.")
    async with session_scope() as session:
        user = await session.scalar(select(User).where(User.email == email))
        password_valid = verify_login_password(user, password)
        valid = bool(password_valid and user.is_admin and user.role in {"owner", "staff"})
        user_id = user.id if valid else None
        version = user.security_version if valid else 0
        enrolled = bool(valid and user.mfa_secret)
        audit(session, request, "admin_password", target=user_id, outcome="success" if valid else "failed")
        await session.commit()
    if not valid:
        return _page(request, "admin/login.html", status=400, error="Invalid email or password.")
    if enrolled:
        return begin_admin_mfa(user_id, version)
    # Operator MFA is opt-in: a password alone signs in when no authenticator is enrolled.
    response = redirect("/admin/")
    response.add_cookie(
        ADMIN_COOKIE,
        await create_session_token(user_id, "admin", expected_version=version),
        max_age=ADMIN_SESSION_MAX_AGE,
        httponly=True,
        secure=not get_settings().debug,
        samesite="Lax",
    )
    return response


@bp.post("/logout")
async def logout(request):
    """Clear the admin session cookie."""
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)
    response = redirect("/admin/login")
    user = request.ctx.admin
    async with session_scope() as db:
        audit(db, request, "admin_logout", actor=user.id if user else None, target=user.id if user else None)
        await db.commit()
    await revoke_session(request.cookies.get(ADMIN_COOKIE, ""))
    response.delete_cookie(ADMIN_COOKIE)
    return response


# --------------------------------------------------------------------------- #
# Dashboard + CRUD
# --------------------------------------------------------------------------- #
async def _booked_weddings(db, *, limit: int) -> tuple[list[dict], int]:
    """Partially paid event work, shown separately from paid Order records."""
    paid = (
        select(
            WeddingInvoice.quote_id,
            func.sum(WeddingInvoice.amount_cents).label("paid_cents"),
            func.count(WeddingInvoice.id).label("paid_count"),
        )
        .where(WeddingInvoice.status == "paid")
        .group_by(WeddingInvoice.quote_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(WeddingQuote, Inquiry, paid.c.paid_cents, paid.c.paid_count)
            .join(paid, paid.c.quote_id == WeddingQuote.id)
            .join(Inquiry, Inquiry.id == WeddingQuote.inquiry_id)
            .where(
                WeddingQuote.order_id.is_(None),
                WeddingQuote.payment_mode.in_(("deposit", "installments")),
                WeddingQuote.status.in_(
                    (
                        "deposit_paid",
                        "balance_sent",
                        "installment_paid",
                        "installment_sent",
                        "amendment_ready",
                        "amendment_sent",
                        "issuing",
                        "review",
                    )
                ),
            )
            .order_by(WeddingQuote.id.desc())
        )
    ).all()
    refund_totals = (
        await db.execute(
            select(WeddingInvoice.quote_id, func.sum(InvoiceRefund.amount_cents))
            .join(InvoiceRefund, InvoiceRefund.wedding_invoice_id == WeddingInvoice.id)
            .where(InvoiceRefund.status == "succeeded")
            .group_by(WeddingInvoice.quote_id)
        )
    ).all()
    refunds_by_quote = dict(refund_totals)
    booked = []
    for quote, inquiry, paid_cents, paid_count in rows:
        total = (quote.snapshot or {}).get("total_cents", 0)
        refunded = refunds_by_quote.get(quote.id, 0)
        amended = (
            quote.amendments[-1] if quote.status in ("amendment_ready", "amendment_sent") and quote.amendments else None
        )
        if paid_cents <= refunded or (not amended and not 0 < paid_cents < total):
            continue
        if amended:
            next_label = "Revised balance"
            next_due = quote.amendment_due_date
            next_send = None
        elif quote.payment_mode == "deposit":
            next_label = "Balance"
            next_due = quote.balance_due_date
            next_send = quote.balance_send_date if quote.balance_send_mode == "automatic" else None
        else:
            parts = quote.installments or []
            part = parts[paid_count] if paid_count < len(parts) else None
            next_label = f"Installment {paid_count + 1} of {len(parts)}" if part else "Review plan"
            next_due = date.fromisoformat(part["due_date"]) if part else None
            next_send = date.fromisoformat(part["send_date"]) if part and part["send_mode"] == "automatic" else None
        balance = amended["amount_cents"] if amended else total - paid_cents
        booked.append(
            dict(
                quote=quote,
                inquiry=inquiry,
                paid_cents=paid_cents,
                refunded_cents=refunded,
                balance_cents=balance,
                next_label=next_label,
                next_due=next_due,
                next_send=next_send,
            )
        )
    return booked[:limit], len(booked)


@bp.get("/")
async def dashboard(request):
    """Render the operator dashboard with upcoming work and reminders."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    counts = {}
    async with session_scope() as session:
        for admin in REGISTRY:
            counts[admin.slug] = await session.scalar(select(func.count()).select_from(admin.model))
        today = datetime.now(ZoneInfo("America/New_York")).date()
        upcoming = (
            await session.scalars(
                select(Order)
                .options(selectinload(Order.customer).selectinload(User.profile))
                .where(
                    Order.status == "paid",
                    Order.fulfillment_state != "completed",
                    Order.fulfillment_date >= today,
                    Order.fulfillment_date <= today + timedelta(days=7),
                )
                .order_by(Order.fulfillment_date, Order.fulfillment_time, Order.id)
                .limit(30)
            )
        ).all()
        outstanding = await session.scalar(
            select(func.count())
            .select_from(Order)
            .where(Order.status == "paid", Order.fulfillment_state != "completed")
        )
        new_inquiries = await session.scalar(
            select(func.count()).select_from(Inquiry).where(Inquiry.handled.is_(False))
        )
        due_inquiries = (
            await session.scalars(
                select(Inquiry)
                .where(Inquiry.follow_up_date.is_not(None), Inquiry.follow_up_date <= today, Inquiry.stage != "closed")
                .order_by(Inquiry.follow_up_date, Inquiry.id)
                .limit(30)
            )
        ).all()
        pending_florists = await session.scalar(
            select(func.count()).select_from(FloristProfile).where(FloristProfile.approved.is_(False))
        )
        low_stock = (
            await session.scalars(
                select(FlowerListing)
                .where(
                    FlowerListing.active.is_(True),
                    FlowerListing.quantity_available <= FlowerListing.low_stock_threshold,
                )
                .order_by(FlowerListing.quantity_available, FlowerListing.id)
                .limit(30)
            )
        ).all()
        booked_weddings, booked_wedding_count = await _booked_weddings(session, limit=10)
    return _page(
        request,
        "admin/dashboard.html",
        counts=counts,
        upcoming=upcoming,
        outstanding=outstanding,
        new_inquiries=new_inquiries,
        pending_florists=pending_florists,
        low_stock=low_stock,
        today=today,
        due_inquiries=due_inquiries,
        booked_weddings=booked_weddings,
        booked_wedding_count=booked_wedding_count,
    )


@bp.get("/inquiries/<pk:int>/photo")
async def inquiry_private_photo(request, pk: int):
    """Stream a private inquiry photo to a signed-in operator."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    async with session_scope() as db:
        inquiry = await db.get(Inquiry, pk)
        key = inquiry.photo if inquiry else ""
    if not key:
        return json({"detail": "Photo not found."}, status=404)

    try:
        content, content_type = await asyncio.to_thread(read_private_image, key)
    except FileNotFoundError, ValueError:
        return json({"detail": "Private photo unavailable. Check storage before retrying."}, status=404)
    except Exception:
        return json({"detail": "Private photo storage unavailable."}, status=503)
    return raw(
        content,
        content_type=content_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
        },
    )


@bp.post("/inquiries/<pk:int>/correspondence")
async def record_inquiry_correspondence(request, pk: int):
    """Save an operator note about an inquiry conversation."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)
    direction = str(request.form.get("direction", "")).strip()
    subject = str(request.form.get("subject", "")).strip()
    summary = str(request.form.get("summary", "")).strip()
    if direction not in ("sent", "received") or not 1 <= len(subject) <= 200 or not 1 <= len(summary) <= 4000:
        return json(
            {"detail": "Choose sent or received, a subject (up to 200), and a summary (up to 4,000)."}, status=400
        )
    async with session_scope() as db:
        if not await db.get(Inquiry, pk):
            return json({"detail": "Inquiry not found."}, status=404)
        db.add(
            InquiryCorrespondence(
                inquiry_id=pk, actor_id=request.ctx.admin.id, direction=direction, subject=subject, summary=summary
            )
        )
        await db.commit()
    return redirect(f"/admin/inquiries/{pk}")


@bp.post("/inquiries/<pk:int>/follow-up")
async def inquiry_follow_up(request, pk: int):
    """Update an inquiry's stage, follow-up date and internal notes."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)
    stage = str(request.form.get("stage", ""))
    raw_date = str(request.form.get("follow_up_date", "")).strip()
    notes = str(request.form.get("internal_notes", "")).strip()
    if stage not in ("new", "contacted", "quoted", "booked", "closed") or len(notes) > 4000:
        return json({"detail": "Choose a valid stage and notes up to 4000 characters."}, status=400)
    try:
        follow_up = date.fromisoformat(raw_date) if raw_date else None
    except ValueError:
        return json({"detail": "Enter a valid follow-up date."}, status=400)
    async with session_scope() as db:
        inquiry = await db.get(Inquiry, pk)
        if not inquiry:
            return json({"detail": "Inquiry not found."}, status=404)
        inquiry.stage = stage
        inquiry.handled = stage == "closed"
        inquiry.follow_up_date = follow_up
        inquiry.internal_notes = notes
        await db.commit()
    return redirect(f"/admin/inquiries/{pk}")


@bp.post("/inquiries/<pk:int>/import-email")
async def import_inquiry_email(request, pk: int):
    """Import one address-verified email into an inquiry history."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)
    upload = request.files.get("email_file")
    if not upload:
        return json({"detail": "Choose an exported .eml email."}, status=400)
    async with session_scope() as db:
        inquiry = await db.scalar(select(Inquiry).where(Inquiry.id == pk).with_for_update())
        if not inquiry:
            return json({"detail": "Inquiry not found."}, status=404)
        try:
            values = parse_email(upload.body, inquiry.email, str(request.form.get("direction", "")))
        except ValueError as exc:
            return json({"detail": str(exc)}, status=400)
        existing = await db.scalar(
            select(InquiryCorrespondence).where(InquiryCorrespondence.source_id == values["source_id"])
        )
        if existing and existing.inquiry_id != pk:
            return json({"detail": "This email was already imported for another inquiry."}, status=409)
        if not existing:
            db.add(InquiryCorrespondence(inquiry_id=pk, actor_id=request.ctx.admin.id, **values))
            await db.commit()
    return redirect(f"/admin/inquiries/{pk}")


@bp.get("/<slug:str>")
async def model_list(request, slug: str):
    """Render a paginated, searchable list for a registry model."""
    admin = REGISTRY_BY_SLUG.get(slug)
    if admin is None:
        return redirect("/admin/")
    if not request.ctx.admin:
        return redirect("/admin/login")
    query = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "") if slug == "orders" else ""
    season_filter = request.args.get("season", "") if slug == "flowers" else ""
    if season_filter not in ("", "spring", "summer", "fall", "winter", "year_round"):
        season_filter = ""
    if status_filter not in ("", "pending", "paid", "refunded", "cancelled", "expired"):
        status_filter = ""
    try:
        page_number = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page_number = 1
    page_number = min(page_number, 100000)
    page_size = 30
    booked_weddings, booked_wedding_count = [], 0
    async with session_scope() as session:
        statement = select(admin.model).options(
            *_relationship_options(
                admin.model,
                [path for _, path in admin.list_columns] + list(admin.eager),
            )
        )
        if query and admin.search:
            statement = statement.where(or_(*[getattr(admin.model, name).ilike(f"%{query}%") for name in admin.search]))
        if status_filter:
            statement = statement.where(Order.status == status_filter)
        if season_filter:
            statement = statement.where(FlowerListing.season == season_filter)
        total = await session.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
        rows = (
            (
                await session.execute(
                    statement.order_by(*_order_columns(admin.model, admin.order_by))
                    .limit(page_size)
                    .offset((page_number - 1) * page_size)
                )
            )
            .scalars()
            .all()
        )
        display = [[(_display_value(row, column), column) for _, column in admin.list_columns] for row in rows]
        if slug == "orders":
            booked_weddings, booked_wedding_count = await _booked_weddings(session, limit=30)
    return _page(
        request,
        "admin/list.html",
        admin=admin,
        rows=rows,
        display=display,
        query=query,
        page_number=page_number,
        pages=max(1, (total + page_size - 1) // page_size),
        total=total,
        status_filter=status_filter,
        season_filter=season_filter,
        booked_weddings=booked_weddings,
        booked_wedding_count=booked_wedding_count,
    )


@bp.get("/<slug:str>/new")
async def model_new(request, slug: str):
    """Render the create form for a registry model."""
    admin = REGISTRY_BY_SLUG.get(slug)
    if admin is None or not admin.can_create:
        return redirect("/admin/")
    if not request.ctx.admin:
        return redirect("/admin/login")
    rows = [_field_row(None, f) for f in admin.fields]
    gallery_options = []
    if slug == "gallery":
        for row in rows:
            if row["field"].name in ("focal_x", "focal_y"):
                row["value"] = 50
    if slug == "flowers":
        async with session_scope() as db:
            gallery_options = (
                await db.scalars(select(GalleryImage).order_by(GalleryImage.sort_order, GalleryImage.id))
            ).all()
    return _page(request, "admin/edit.html", admin=admin, obj=None, rows=rows, gallery_options=gallery_options)


@bp.post("/<slug:str>/new")
async def model_create(request, slug: str):
    """Create and persist a registry model entry from a submitted form."""
    admin = REGISTRY_BY_SLUG.get(slug)
    if admin is None or not admin.can_create:
        return redirect("/admin/")
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)
    if slug == "flowers" and (error := _flower_delivery_fee_error(request.form)):
        return json({"detail": error}, status=400)
    if slug == "announcements" and (error := _announcement_error(request.form)):
        return json({"detail": error}, status=400)
    if slug == "gallery" and (error := _gallery_error(request.form)):
        return json({"detail": error}, status=400)
    if slug == "gallery" and not request.files.get("image"):
        return json({"detail": "Upload an image for the gallery."}, status=400)
    async with session_scope() as session:
        obj = admin.model()
        try:
            chosen_image = await _selected_gallery_image(session, request.form, request.files, slug)
            await _apply_form(obj, admin, request.form, request.files)
        except ValueError as exc:
            return json({"detail": str(exc)}, status=400)
        except Exception:
            return json({"detail": "Image storage unavailable; nothing was saved."}, status=503)
        if chosen_image:
            obj.photo = chosen_image.image
        if slug == "flowers":
            initial = obj.quantity_available or 0
            if initial < 0:
                return json({"detail": "Starting quantity cannot be negative."}, status=400)
            obj.quantity_available = 0
            session.add(obj)
            await session.flush()
            await change_stock(
                session,
                obj,
                initial,
                kind="restock" if initial else "opening",
                units=initial,
                actor_id=request.ctx.admin.id,
                reason="Initial stock",
                source="admin",
            )
        session.add(obj)
        await session.commit()
    return redirect(f"/admin/{slug}")


@bp.get("/<slug:str>/<pk:int>")
async def model_edit(request, slug: str, pk: int):
    """Render the edit form for a registry model entry."""
    admin = REGISTRY_BY_SLUG.get(slug)
    if admin is None:
        return redirect("/admin/")
    if not request.ctx.admin:
        return redirect("/admin/login")
    async with session_scope() as session:
        options = _relationship_options(
            admin.model,
            [f.name for f in admin.fields] + list(admin.eager),
        )
        if slug == "orders":
            options.append(selectinload(Order.items))
        obj = await session.scalar(select(admin.model).options(*options).where(admin.model.id == pk))
    if obj is None:
        return redirect(f"/admin/{slug}")
    rows = [
        _field_row(
            obj, Field(f.name, f.label, "readonly") if slug == "flowers" and f.name == "quantity_available" else f
        )
        for f in admin.fields
    ]
    order_total = None
    order_proposal = None
    refunds = []
    correspondence = []
    if slug == "inquiries":
        async with session_scope() as db:
            correspondence = (
                await db.scalars(
                    select(InquiryCorrespondence)
                    .where(InquiryCorrespondence.inquiry_id == pk)
                    .order_by(InquiryCorrespondence.occurred_at.desc(), InquiryCorrespondence.id.desc())
                    .limit(100)
                )
            ).all()
    if slug == "orders":
        order_total = sum((item.price_snapshot * item.quantity for item in obj.items), Decimal("0")) + obj.delivery_fee
        async with session_scope() as db:
            order_proposal = await db.scalar(select(BouquetProposal).where(BouquetProposal.order_id == pk))
            refunds = (
                await db.scalars(select(OrderRefund).where(OrderRefund.order_id == pk).order_by(OrderRefund.id.desc()))
            ).all()
        if order_proposal and order_proposal.history:
            order_total = Decimal(order_proposal.history[-1]["draft"]["total_cents"]) / 100
    gallery_options = []
    if slug == "flowers":
        async with session_scope() as db:
            gallery_options = (
                await db.scalars(select(GalleryImage).order_by(GalleryImage.sort_order, GalleryImage.id))
            ).all()
    return _page(
        request,
        "admin/edit.html",
        admin=admin,
        obj=obj,
        rows=rows,
        order_total=order_total,
        order_proposal=order_proposal,
        refunds=refunds,
        gallery_options=gallery_options,
        correspondence=correspondence,
        refund_key=str(uuid.uuid4()),
        proposal_id=(await _proposal_for_inquiry(pk)) if slug == "inquiries" and obj.kind == "bouquet" else None,
    )


async def _proposal_for_inquiry(inquiry_id: int) -> int | None:
    async with session_scope() as db:
        return await db.scalar(select(BouquetProposal.id).where(BouquetProposal.inquiry_id == inquiry_id))


@bp.get("/weddings/from-inquiry/<inquiry_id:int>")
async def wedding_start(request, inquiry_id: int):
    """Open or create the event quote for a wedding inquiry."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    async with session_scope() as db:
        inquiry = await db.get(Inquiry, inquiry_id)
        if not inquiry or inquiry.kind != "wedding":
            return json({"detail": "Only wedding inquiries can become event quotes."}, status=404)
        quote = await db.scalar(select(WeddingQuote).where(WeddingQuote.inquiry_id == inquiry_id))
    if quote:
        return redirect(f"/admin/weddings/{quote.id}")
    return _page(request, "admin/wedding.html", inquiry=inquiry, quote=None, invoices=[], draft={})


@bp.get("/weddings/")
async def weddings_list(request):
    """List the most recent wedding quotes."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    async with session_scope() as db:
        quotes = (await db.scalars(select(WeddingQuote).order_by(WeddingQuote.id.desc()).limit(100))).all()
    return _page(request, "admin/weddings.html", quotes=quotes)


@bp.post("/weddings/from-inquiry/<inquiry_id:int>")
async def wedding_create(request, inquiry_id: int):
    """Create a draft wedding quote from a wedding inquiry."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)
    async with session_scope() as db:
        inquiry = await db.get(Inquiry, inquiry_id)
        if not inquiry or inquiry.kind != "wedding":
            return json({"detail": "Only wedding inquiries can become event quotes."}, status=404)
        existing = await db.scalar(select(WeddingQuote).where(WeddingQuote.inquiry_id == inquiry_id))
        if existing:
            return redirect(f"/admin/weddings/{existing.id}")
        quote = WeddingQuote(
            inquiry_id=inquiry_id,
            draft=dict(
                title="Wedding floral design",
                description=inquiry.message or "",
                location=str((inquiry.details or {}).get("venue", "")),
                terms="Seasonal flowers may be substituted with blooms of similar value and style.",
                lines=[],
            ),
            snapshot={},
            activity=[],
        )
        db.add(quote)
        await db.commit()
    return redirect(f"/admin/weddings/{quote.id}")


@bp.get("/weddings/<quote_id:int>")
async def wedding_detail(request, quote_id: int):
    """Render a wedding quote with its invoices and refunds."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    async with session_scope() as db:
        quote = await db.get(WeddingQuote, quote_id)
        inquiry = await db.get(Inquiry, quote.inquiry_id) if quote else None
        invoices = (
            (
                await db.scalars(
                    select(WeddingInvoice).where(WeddingInvoice.quote_id == quote_id).order_by(WeddingInvoice.id)
                )
            ).all()
            if quote
            else []
        )
        invoice_refunds = (
            (
                await db.scalars(
                    select(InvoiceRefund)
                    .where(InvoiceRefund.wedding_invoice_id.in_([invoice.id for invoice in invoices]))
                    .order_by(InvoiceRefund.id)
                )
            ).all()
            if invoices
            else []
        )

        next_part_index = (
            await next_installment_index(db, quote) if quote and quote.status == "installment_paid" else None
        )
    if not quote:
        return json({"detail": "Quote not found."}, status=404)
    latest_amendment = (quote.amendments or [])[-1] if quote.amendments else None
    return _page(
        request,
        "admin/wedding.html",
        quote=quote,
        inquiry=inquiry,
        invoices=invoices,
        draft=quote.draft
        if quote.status == "draft"
        else latest_amendment["draft"]
        if latest_amendment
        else quote.snapshot,
        next_part_index=next_part_index,
        latest_amendment=latest_amendment,
        refunds_by_invoice={
            row.id: [entry for entry in invoice_refunds if entry.wedding_invoice_id == row.id] for row in invoices
        },
        refund_keys={row.id: str(uuid.uuid4()) for row in invoices},
    )


@bp.post("/weddings/<quote_id:int>/save")
async def wedding_save(request, quote_id: int):
    """Validate and save edits to a draft wedding quote."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)

    try:
        draft, mode, deposit = validate_quote(request.form)
        if mode == "installments":
            parts = validate_installments(request.form, draft["total_cents"])
            first = parts[0]
            schedule = dict(
                initial_send_mode=first["send_mode"],
                initial_send_date=date.fromisoformat(first["send_date"]) if first["send_date"] else None,
                initial_due_date=date.fromisoformat(first["due_date"]),
                balance_send_mode="manual",
                balance_send_date=None,
                balance_due_date=None,
            )
        else:
            parts = []
            schedule = validate_schedule(request.form, mode)
    except ValueError as exc:
        return json(
            {"detail": str(exc), **({"field": exc.field} if isinstance(exc, FieldValidationError) else {})}, status=400
        )
    async with session_scope() as db:
        quote = await db.scalar(select(WeddingQuote).where(WeddingQuote.id == quote_id).with_for_update())
        if not quote or quote.status != "draft":
            return json({"detail": "Only unsent quotes can be edited."}, status=409)
        quote.draft, quote.payment_mode, quote.deposit_cents = draft, mode, deposit
        quote.installments = parts
        for name, value in schedule.items():
            setattr(quote, name, value)
        await db.commit()
    return redirect(f"/admin/weddings/{quote_id}")


@bp.post("/weddings/<quote_id:int>/amend")
async def wedding_amend(request, quote_id: int):
    """Record a customer-accepted revision to a partially paid wedding."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)

    try:
        await agree_revised_wedding(quote_id, request.form, actor_id=request.ctx.admin.id)
    except ValueError as exc:
        return json(
            {"detail": str(exc), **({"field": exc.field} if isinstance(exc, FieldValidationError) else {})}, status=409
        )
    return redirect(f"/admin/weddings/{quote_id}")


@bp.post("/weddings/<quote_id:int>/schedule")
async def wedding_schedule_approve(request, quote_id: int):
    """Approve a wedding quote for automatic invoice sending."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)

    try:
        await approve_wedding_schedule(quote_id)
    except ValueError as exc:
        return json({"detail": str(exc)}, status=409)
    return redirect(f"/admin/weddings/{quote_id}")


@bp.post("/weddings/<quote_id:int>/send/<step:str>")
async def wedding_send(request, quote_id: int, step: str):
    """Send the requested wedding invoice step."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)

    try:
        await send_wedding_invoice(quote_id, step)
    except ValueError as exc:
        return json({"detail": str(exc)}, status=409)
    except Exception:
        return json({"detail": "Invoice outcome uncertain. Review Stripe before retrying."}, status=503)
    return redirect(f"/admin/weddings/{quote_id}")


@bp.post("/weddings/<quote_id:int>/refresh/<invoice_id:int>")
async def wedding_refresh(request, quote_id: int, invoice_id: int):
    """Reconcile a wedding invoice against Stripe."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)
    async with session_scope() as db:
        invoice = await db.get(WeddingInvoice, invoice_id)
        if not invoice or invoice.quote_id != quote_id:
            return json({"detail": "Invoice not found."}, status=404)

    try:
        result = await reconcile_wedding_invoice(invoice_id)
    except ValueError as exc:
        return json({"detail": str(exc)}, status=409)
    except Exception:
        return json({"detail": "Stripe unavailable. Try again later."}, status=503)
    if result == "review":
        return json({"detail": "Invoice requires payment review in Stripe."}, status=409)
    return redirect(f"/admin/weddings/{quote_id}")


@bp.post("/weddings/<quote_id:int>/revise/<invoice_id:int>")
async def wedding_revise_invoice(request, quote_id: int, invoice_id: int):
    """Void an outstanding wedding invoice before reissuing it."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)

    try:
        await revise_wedding_invoice(quote_id, invoice_id, actor_id=request.ctx.admin.id)
    except ValueError as exc:
        return json({"detail": str(exc)}, status=409)
    return redirect(f"/admin/weddings/{quote_id}")


@bp.post("/weddings/<quote_id:int>/attach/<invoice_id:int>")
async def wedding_attach_reviewed_invoice(request, quote_id: int, invoice_id: int):
    """Attach an operator-supplied Stripe invoice to a quote."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)

    try:
        await attach_reviewed_wedding_invoice(
            quote_id, invoice_id, str(request.form.get("stripe_invoice_id", "")), actor_id=request.ctx.admin.id
        )
    except ValueError as exc:
        return json({"detail": str(exc)}, status=409)
    return redirect(f"/admin/weddings/{quote_id}")


@bp.post("/invoice-refunds/<kind:str>/<pk:int>")
async def refund_invoice_payment(request, kind: str, pk: int):
    """Refund one verified Stripe invoice payment."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)

    try:
        refund = await issue_invoice_refund(kind, pk, request.form, request.ctx.admin.id)
    except ValueError as exc:
        return json({"detail": str(exc)}, status=409)
    if refund.status != "succeeded":
        return json({"detail": "Refund is not confirmed. Review Stripe before taking further action."}, status=409)
    if kind == "wedding":
        async with session_scope() as db:
            quote_id = await db.scalar(select(WeddingInvoice.quote_id).where(WeddingInvoice.id == pk))
        return redirect(f"/admin/weddings/{quote_id}")
    return redirect(f"/admin/proposals/{pk}")


@bp.post("/invoice-refunds/<refund_id:int>/refresh")
async def refresh_invoice_refund(request, refund_id: int):
    """Reconcile a recorded invoice refund against Stripe."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)

    async with session_scope() as db:
        refund = await db.get(InvoiceRefund, refund_id)
        if not refund:
            return json({"detail": "Refund not found."}, status=404)
        if refund.wedding_invoice_id:
            quote_id = await db.scalar(
                select(WeddingInvoice.quote_id).where(WeddingInvoice.id == refund.wedding_invoice_id)
            )
            destination = f"/admin/weddings/{quote_id}"
        else:
            destination = f"/admin/proposals/{refund.proposal_id}"
    try:
        status = await reconcile_invoice_refund(refund_id)
    except ValueError as exc:
        return json({"detail": str(exc)}, status=409)
    if status == "review":
        return json(
            {"detail": "Stripe has not confirmed this refund. Check Stripe before another request."}, status=409
        )
    return redirect(destination)


@bp.post("/invoice-refunds/<kind:str>/<pk:int>/import")
async def import_invoice_refund(request, kind: str, pk: int):
    """Verify an existing Stripe refund before importing its journal entry."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)
    try:
        await import_external_invoice_refund(
            kind, pk, str(request.form.get("stripe_refund_id", "")).strip(), request.ctx.admin.id
        )
    except ValueError as exc:
        return json({"detail": str(exc)}, status=409)
    if kind == "wedding":
        async with session_scope() as db:
            quote_id = await db.scalar(select(WeddingInvoice.quote_id).where(WeddingInvoice.id == pk))
        return redirect(f"/admin/weddings/{quote_id}")
    return redirect(f"/admin/proposals/{pk}")


@bp.post("/invoice-refunds/<kind:str>/<pk:int>/close")
async def close_refunded_quote(request, kind: str, pk: int):
    """Close a fully refunded, review-state wedding or bouquet quote."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)

    try:
        await close_fully_refunded_quote(kind, pk, request.ctx.admin.id)
    except ValueError as exc:
        return json({"detail": str(exc)}, status=409)
    return redirect(f"/admin/{'weddings' if kind == 'wedding' else 'proposals'}/{pk}")


@bp.post("/orders/<pk:int>/refund")
async def refund_order(request, pk: int):
    """Issue an idempotent refund for a paid order."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)

    try:
        refund = await issue_refund(pk, request.form, request.ctx.admin.id)
    except ValueError as exc:
        return json({"detail": str(exc)}, status=409)
    if refund.status != "succeeded":
        return json({"detail": "Refund is not confirmed. Check Stripe before taking further action."}, status=409)
    return redirect(f"/admin/orders/{pk}")


@bp.post("/orders/<pk:int>/fulfillment")
async def update_fulfillment(request, pk: int):
    """Save an order's schedule, preparation state and internal notes."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)
    raw_date = str(request.form.get("fulfillment_date", "")).strip()
    raw_time = str(request.form.get("fulfillment_time", "")).strip()
    state = str(request.form.get("fulfillment_state", "")).strip()
    notes = str(request.form.get("internal_notes", "")).strip()
    try:
        scheduled_date = date.fromisoformat(raw_date) if raw_date else None
        scheduled_time = time.fromisoformat(raw_time) if raw_time else None
    except ValueError:
        return json({"detail": "Enter a valid schedule date and time."}, status=400)
    if (
        (scheduled_time and not scheduled_date)
        or state not in ("new", "preparing", "ready", "completed")
        or len(notes) > 4000
    ):
        return json(
            {"detail": "Enter a valid preparation state, schedule and notes (up to 4000 characters)."}, status=400
        )
    async with session_scope() as db:
        order = await db.scalar(select(Order).where(Order.id == pk).with_for_update())
        if order is None:
            return json({"detail": "Order not found."}, status=404)
        if order.status != "paid":
            return json({"detail": "Only paid orders can be scheduled or prepared."}, status=409)
        if order.fulfilled_at and state != "completed":
            return json({"detail": "A completed order cannot be reopened."}, status=409)
        before = (order.fulfillment_date, order.fulfillment_time, order.fulfillment_state, order.internal_notes)
        after = (scheduled_date, scheduled_time, state, notes)
        if before != after:
            order.fulfillment_date, order.fulfillment_time, order.fulfillment_state, order.internal_notes = after
            if state == "completed" and not order.fulfilled_at:
                order.fulfilled_at = datetime.now(UTC)
            order.activity = [
                *(order.activity or []),
                dict(
                    action="fulfillment updated",
                    actor=request.ctx.admin.id,
                    at=datetime.now(UTC).isoformat(),
                    from_state=before[2],
                    to_state=state,
                    date=scheduled_date.isoformat() if scheduled_date else None,
                    time=scheduled_time.isoformat(timespec="minutes") if scheduled_time else None,
                ),
            ]
            await db.commit()
    return redirect(f"/admin/orders/{pk}")


@bp.get("/orders/<pk:int>/packing-slip")
async def packing_slip(request, pk: int):
    """Render a printable packing slip for a paid order."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    async with session_scope() as db:
        order = await db.scalar(
            select(Order)
            .options(selectinload(Order.items), selectinload(Order.customer).selectinload(User.profile))
            .where(Order.id == pk)
        )
        proposal = await db.scalar(select(BouquetProposal).where(BouquetProposal.order_id == pk)) if order else None
    if not order or order.status != "paid":
        return json({"detail": "No paid order found."}, status=404)
    return _page(request, "admin/packing_slip.html", order=order, proposal=proposal)


@bp.get("/orders/manual/new")
async def manual_order_page(request):
    """Render the form for recording an off-site payment."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    async with session_scope() as db:
        listings = (
            await db.scalars(select(FlowerListing).where(FlowerListing.active.is_(True)).order_by(FlowerListing.name))
        ).all()
    return _page(request, "admin/manual_order.html", listings=listings, manual_key=str(uuid.uuid4()))


@bp.post("/orders/manual/new")
async def manual_order_submit(request):
    """Record and stock a manual off-site order."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)

    try:
        async with session_scope() as db:
            order = await create_manual_order(db, request.form, request.ctx.admin.id)
            order_id = order.id
    except (ValueError, StockError) as exc:
        return json(
            {"detail": str(exc), **({"field": exc.field} if isinstance(exc, FieldValidationError) else {})}, status=400
        )
    except IntegrityError:
        # A repeated submission racing the first one must not charge stock twice.
        async with session_scope() as db:
            order_id = await db.scalar(
                select(Order.id).where(Order.manual_key == str(request.form.get("manual_key", "")))
            )
        if order_id is None:
            return json({"detail": "Order could not be recorded. Check the order list before retrying."}, status=409)
    await deliver_notifications(order_id)
    return redirect(f"/admin/orders/{order_id}")


@bp.get("/reports/sales")
async def sales_report(request):
    """Render or export paid and refunded order totals."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    try:
        start = date.fromisoformat(request.args.get("from")) if request.args.get("from") else None
        end = date.fromisoformat(request.args.get("to")) if request.args.get("to") else None
    except ValueError:
        return json({"detail": "Use YYYY-MM-DD for report dates."}, status=400)
    if start and end and end < start:
        return json({"detail": "End date must be on or after start date."}, status=400)
    async with session_scope() as db:
        statement = (
            select(Order)
            .options(selectinload(Order.items), selectinload(Order.customer).selectinload(User.profile))
            .where(Order.status.in_(("paid", "refunded")))
        )
        # Timestamps are stored as UTC; filter on the Eastern calendar boundaries.
        eastern = ZoneInfo("America/New_York")
        if start:
            statement = statement.where(Order.created_at >= datetime.combine(start, time.min, eastern).astimezone(UTC))
        if end:
            statement = statement.where(
                Order.created_at < datetime.combine(end + timedelta(days=1), time.min, eastern).astimezone(UTC)
            )
        orders = (await db.scalars(statement.order_by(Order.created_at.desc(), Order.id.desc()))).all()
        proposal_ids = [order.id for order in orders]
        proposals = (
            (await db.scalars(select(BouquetProposal).where(BouquetProposal.order_id.in_(proposal_ids)))).all()
            if proposal_ids
            else []
        )
        refunds = (
            (
                await db.scalars(
                    select(OrderRefund).where(OrderRefund.order_id.in_(proposal_ids), OrderRefund.status == "succeeded")
                )
            ).all()
            if proposal_ids
            else []
        )
    by_order = {proposal.order_id: proposal for proposal in proposals}
    refunded_by_order: dict[int, int] = {}
    for refund in refunds:
        refunded_by_order[refund.order_id] = refunded_by_order.get(refund.order_id, 0) + refund.amount_cents
    rows = []
    for order in orders:
        proposal = by_order.get(order.id)
        total = (
            Decimal(proposal.history[-1]["draft"]["total_cents"]) / 100
            if proposal and proposal.history
            else sum((item.price_snapshot * item.quantity for item in order.items), Decimal("0")) + order.delivery_fee
        )
        recorded_cents = refunded_by_order.get(order.id)
        refunded = (
            None
            if order.status == "refunded" and recorded_cents != int(total * 100)
            else Decimal(recorded_cents) / 100
            if recorded_cents is not None
            else Decimal("0")
        )
        rows.append(
            dict(order=order, total=total, refunded=refunded, net=total - refunded if refunded is not None else None)
        )
    if request.args.get("format") == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            (
                "Order",
                "Placed UTC",
                "Customer",
                "Channel",
                "Payment method",
                "Payment reference",
                "Status",
                "Original gross USD",
                "Recorded refunded USD",
                "Recorded net USD",
            )
        )

        def safe(value):
            value = str(value or "")
            return "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value

        for row in rows:
            order = row["order"]
            writer.writerow(
                (
                    order.order_reference,
                    order.created_at.isoformat(),
                    safe(order.customer_label),
                    order.channel,
                    order.payment_method,
                    safe(order.payment_reference),
                    order.status,
                    f"{row['total']:.2f}",
                    f"{row['refunded']:.2f}" if row["refunded"] is not None else "unknown",
                    f"{row['net']:.2f}" if row["net"] is not None else "unknown",
                )
            )
        return text(
            output.getvalue(),
            content_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=honey-summer-sales.csv"},
        )
    totals: dict[str, Decimal] = {}
    for row in rows:
        key = f"{row['order'].payment_method} · {row['order'].status}"
        totals[key] = totals.get(key, Decimal("0")) + row["total"]
    return _page(request, "admin/sales_report.html", rows=rows, totals=totals, start=start, end=end)


@bp.get("/reports/balances")
async def invoice_balances(request):
    """Render or export outstanding invoice balances."""
    if not request.ctx.admin:
        return redirect("/admin/login")

    async with session_scope() as db:
        rows = await invoice_balance_rows(db)
    totals = dict(
        remaining_cents=sum(row["balance_cents"] for row in rows),
        open_cents=sum(row["open_cents"] for row in rows),
        verified_paid_cents=sum(row["verified_paid_cents"] for row in rows),
        refunded_cents=sum(row["refunded_cents"] for row in rows),
    )
    if request.args.get("format") == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            (
                "Type",
                "Reference",
                "Customer",
                "Title",
                "Status",
                "Verified paid USD",
                "Recorded refunded USD",
                "Remaining USD",
                "Open invoice USD",
                "Estimated due Eastern",
                "Needs review",
            )
        )

        def safe(value):
            value = str(value or "")
            return "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value

        for row in rows:
            writer.writerow(
                (
                    row["kind"],
                    row["id"],
                    safe(row["customer"]),
                    safe(row["title"]),
                    row["status"],
                    f"{row['verified_paid_cents'] / 100:.2f}",
                    f"{row['refunded_cents'] / 100:.2f}",
                    f"{row['balance_cents'] / 100:.2f}",
                    f"{row['open_cents'] / 100:.2f}",
                    row["due"] or "",
                    row["needs_review"],
                )
            )
        return text(
            output.getvalue(),
            content_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=honey-summer-invoice-balances.csv"},
        )
    return _page(request, "admin/invoice_balances.html", rows=rows, totals=totals)


@bp.get("/reports/operations")
async def operations_report(request):
    """Render or export stock-loss and product-sales history."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    try:
        start = date.fromisoformat(request.args.get("from")) if request.args.get("from") else None
        end = date.fromisoformat(request.args.get("to")) if request.args.get("to") else None
    except ValueError:
        return json({"detail": "Use YYYY-MM-DD for report dates."}, status=400)
    if start and end and end < start:
        return json({"detail": "End date must be on or after start date."}, status=400)

    async with session_scope() as db:
        waste, products, channels = await operations_rows(db, start, end)
    if request.args.get("format") == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            (
                "Section",
                "Reference",
                "Name",
                "Channel / source",
                "Payment",
                "Status",
                "Orders",
                "Units",
                "Original gross USD",
                "Reason",
                "Date UTC",
            )
        )

        def safe(value):
            value = str(value or "")
            return "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value

        for row in waste:
            writer.writerow(
                (
                    "Waste",
                    row["code"],
                    safe(row["name"]),
                    safe(row["source"]),
                    "",
                    "",
                    "",
                    row["units"],
                    "",
                    safe(row["reason"]),
                    row["date"].isoformat(),
                )
            )
        for row in products:
            writer.writerow(
                (
                    "Product",
                    row["listing_id"] or "Custom",
                    safe(row["name"]),
                    row["channel"],
                    "",
                    row["status"],
                    row["orders"],
                    row["units"],
                    f"{row['gross']:.2f}",
                    "",
                    "",
                )
            )
        for row in channels:
            writer.writerow(
                (
                    "Channel",
                    "",
                    "",
                    row["channel"],
                    row["payment"],
                    row["status"],
                    row["orders"],
                    "",
                    f"{row['gross']:.2f}",
                    "",
                    "",
                )
            )
        return text(
            output.getvalue(),
            content_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=honey-summer-operations.csv"},
        )
    return _page(
        request, "admin/operations_report.html", waste=waste, products=products, channels=channels, start=start, end=end
    )


@bp.get("/operations/attention")
async def operations_attention(request):
    """List records that need operator review."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    async with session_scope() as db:
        notices = (
            await db.scalars(
                select(OrderNotification)
                .where(OrderNotification.sent_at.is_(None))
                .order_by(OrderNotification.created_at.desc())
                .limit(200)
            )
        ).all()
        quotes = (
            await db.scalars(
                select(WeddingQuote)
                .where(WeddingQuote.status.in_(("review", "issuing")))
                .order_by(WeddingQuote.id.desc())
                .limit(200)
            )
        ).all()
        proposals = (
            await db.scalars(
                select(BouquetProposal)
                .where(BouquetProposal.status.in_(("review", "issuing", "stock_review")))
                .order_by(BouquetProposal.id.desc())
                .limit(200)
            )
        ).all()
        refunds = (
            await db.scalars(
                select(OrderRefund)
                .where(OrderRefund.status.in_(("review", "issuing")))
                .order_by(OrderRefund.id.desc())
                .limit(200)
            )
        ).all()
        invoice_refunds = (
            await db.scalars(
                select(InvoiceRefund)
                .where(InvoiceRefund.status.in_(("review", "issuing")))
                .order_by(InvoiceRefund.id.desc())
                .limit(200)
            )
        ).all()
        invoice_quote_ids = dict(
            (
                await db.execute(
                    select(WeddingInvoice.id, WeddingInvoice.quote_id).where(
                        WeddingInvoice.id.in_(
                            [row.wedding_invoice_id for row in invoice_refunds if row.wedding_invoice_id is not None]
                        )
                    )
                )
            ).all()
        )
        reconciliation_runs = (
            await db.scalars(select(ReconciliationRun).order_by(ReconciliationRun.id.desc()).limit(20))
        ).all()
        failed_inquiry_mail = (
            await db.scalars(
                select(Inquiry)
                .where(
                    or_(
                        Inquiry.email_delivery["farm"].as_string() == "failed",
                        Inquiry.email_delivery["customer"].as_string() == "failed",
                    )
                )
                .order_by(Inquiry.id.desc())
                .limit(100)
            )
        ).all()
    return _page(
        request,
        "admin/operations_attention.html",
        notices=notices,
        quotes=quotes,
        proposals=proposals,
        refunds=refunds,
        invoice_refunds=invoice_refunds,
        invoice_quote_ids=invoice_quote_ids,
        reconciliation_runs=reconciliation_runs,
        failed_inquiry_mail=failed_inquiry_mail,
    )


@bp.get("/site-content")
async def site_content_page(request):
    """Render the owner-edited storefront content form."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    async with session_scope() as db:
        record = await db.get(SiteContent, 1)
        photos = (
            await db.scalars(
                select(GalleryImage)
                .where(GalleryImage.active.is_(True))
                .order_by(GalleryImage.sort_order, GalleryImage.id)
            )
        ).all()

    checkout = urlsplit(get_settings().retail_checkout_success_url)
    storefront_base = f"{checkout.scheme}://{checkout.netloc}" if checkout.scheme in ("http", "https") else ""
    return _page(
        request,
        "admin/site_content.html",
        content=record.content if record else {},
        saved=bool(record),
        updated_at=record.updated_at if record else None,
        storefront_base=storefront_base,
        photos=photos,
        photo_slots=PHOTO_SLOTS,
    )


@bp.post("/site-content")
async def save_site_content(request):
    """Validate and save owner-edited storefront content."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)

    try:
        content = validate_content(request.form)
    except ValueError as exc:
        return json({"detail": str(exc)}, status=400)
    async with session_scope() as db:
        selected = {}
        for slot in PHOTO_SLOTS:
            raw_id = str(request.form.get(f"photo_{slot}", "")).strip()
            if not raw_id:
                continue
            if not raw_id.isdigit():
                return json({"detail": "Choose a photo from the gallery."}, status=400)
            photo = await db.get(GalleryImage, int(raw_id))
            if not photo or not photo.active or not photo.alt_text.strip():
                return json({"detail": "Selected photos must be active and have alt text."}, status=400)
            selected[slot] = photo.id
        content["photos"] = selected
        record = await db.scalar(select(SiteContent).where(SiteContent.id == 1).with_for_update())
        if not record:
            record = SiteContent(id=1)
            db.add(record)
        record.content = content
        record.updated_by = request.ctx.admin.id
        record.updated_at = datetime.now(UTC)
        await db.commit()
    return redirect("/admin/site-content")


@bp.get("/customers")
async def customer_history(request):
    """Show orders and inquiries for one customer email."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    email = str(request.args.get("email", "")).strip().lower()
    orders = []
    inquiries = []
    if email and "@" in email and len(email) <= 254:
        async with session_scope() as db:
            customer_id = await db.scalar(select(User.id).where(User.email == email))
            clause = (
                or_(func.lower(Order.customer_email) == email, Order.customer_id == customer_id)
                if customer_id
                else func.lower(Order.customer_email) == email
            )
            orders = (await db.scalars(select(Order).where(clause).order_by(Order.created_at.desc()).limit(100))).all()
            inquiries = (
                await db.scalars(
                    select(Inquiry)
                    .where(func.lower(Inquiry.email) == email)
                    .order_by(Inquiry.created_at.desc())
                    .limit(100)
                )
            ).all()
    return _page(request, "admin/customers.html", email=email, orders=orders, inquiries=inquiries)


@bp.get("/proposals/")
async def proposals_list(request):
    """List the most recent bouquet proposals."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    async with session_scope() as db:
        proposals = (await db.scalars(select(BouquetProposal).order_by(BouquetProposal.id.desc()))).all()
    return _page(request, "admin/proposals.html", proposals=proposals)


@bp.get("/proposals/from-inquiry/<inquiry_id:int>")
async def proposal_start_page(request, inquiry_id: int):
    """Open or create the proposal for a bouquet inquiry."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    async with session_scope() as db:
        inquiry = await db.get(Inquiry, inquiry_id)
        existing = await db.scalar(select(BouquetProposal.id).where(BouquetProposal.inquiry_id == inquiry_id))
    if not inquiry or inquiry.kind != "bouquet":
        return json({"detail": "Only bouquet inquiries can become proposals."}, status=404)
    if existing:
        return redirect(f"/admin/proposals/{existing}")
    return _page(request, "admin/proposal.html", inquiry=inquiry, proposal=None, draft={}, error=None)


@bp.post("/proposals/from-inquiry/<inquiry_id:int>")
async def proposal_start(request, inquiry_id: int):
    """Create a draft bouquet proposal from a bouquet inquiry."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)
    async with session_scope() as db:
        inquiry = await db.get(Inquiry, inquiry_id)
        if not inquiry or inquiry.kind != "bouquet":
            return json({"detail": "Only bouquet inquiries can become proposals."}, status=404)
        existing = await db.scalar(select(BouquetProposal.id).where(BouquetProposal.inquiry_id == inquiry_id))
        if existing:
            return redirect(f"/admin/proposals/{existing}")
        details = inquiry.details or {}
        proposal = BouquetProposal(
            inquiry_id=inquiry_id,
            status="draft",
            draft=dict(
                title=f"Custom bouquet — {details['occasion']}"
                if details.get("occasion")
                else "Custom seasonal bouquet",
                description=inquiry.message or "",
                fulfillment=details.get("fulfillment")
                if details.get("fulfillment") in ("pickup", "delivery")
                else "pickup",
                location=str(details.get("desired_date") or ""),
                terms="Seasonal flowers may be substituted with blooms of similar value and style.",
            ),
            history=[],
            activity=[dict(action="created", actor=request.ctx.admin.id, at=datetime.now(UTC).isoformat())],
            internal_notes="",
        )
        db.add(proposal)
        await db.commit()
        return redirect(f"/admin/proposals/{proposal.id}")


def _proposal_form(form) -> dict:

    raw_ids = str(form.get("line_ids", "")).strip()
    if raw_ids:
        tokens = raw_ids.split(",")
        if not all(token.isdigit() and 1 <= int(token) <= 100000 for token in tokens):
            raise FieldValidationError("Proposal line identifiers are invalid.", "line_ids")
        indexes = [int(token) for token in tokens]
    else:
        # Older clients submitted numbered line fields without a row list.
        indexes = sorted(int(match.group(1)) for key in form.keys() if (match := re.fullmatch(r"name_(\d+)", str(key))))
    if len(indexes) != len(set(indexes)) or len(indexes) > 200:
        raise FieldValidationError("Add no more than 200 distinct proposal lines.", "line_ids")
    lines = []
    for index in indexes:
        name = str(form.get(f"name_{index}", "")).strip()
        if not name:
            if any(str(form.get(f"{field}_{index}", "")).strip() for field in ("description", "price", "listing")) or (
                str(form.get(f"quantity_{index}", "")).strip() not in ("", "1")
            ):
                raise FieldValidationError(
                    "Name each proposal line that has details, a price, or a listing.", f"name_{index}"
                )
            continue
        lines.append(
            dict(
                _form_index=index,
                name=name,
                description=form.get(f"description_{index}", ""),
                quantity=form.get(f"quantity_{index}"),
                price=form.get(f"price_{index}"),
                listing_id=form.get(f"listing_{index}"),
            )
        )
    return dict(
        title=form.get("title", ""),
        description=form.get("description", ""),
        terms=form.get("terms", ""),
        fulfillment=form.get("fulfillment", "pickup"),
        location=form.get("location", ""),
        delivery=form.get("delivery", "0"),
        lines=lines,
    )


@bp.get("/proposals/<proposal_id:int>")
async def proposal_detail(request, proposal_id: int):
    """Render a bouquet proposal with its invoices and refunds."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    async with session_scope() as db:
        proposal = await db.get(BouquetProposal, proposal_id)
        inquiry = await db.get(Inquiry, proposal.inquiry_id) if proposal else None
        invoice_refunds = (
            (
                await db.scalars(
                    select(InvoiceRefund).where(InvoiceRefund.proposal_id == proposal_id).order_by(InvoiceRefund.id)
                )
            ).all()
            if proposal
            else []
        )
    if not proposal:
        return json({"detail": "Proposal not found."}, status=404)
    return _page(
        request,
        "admin/proposal.html",
        proposal=proposal,
        inquiry=inquiry,
        draft=proposal.draft,
        invoice_refunds=invoice_refunds,
        refund_key=str(uuid.uuid4()),
        error=None,
    )


@bp.post("/proposals/<proposal_id:int>/save")
async def proposal_save(request, proposal_id: int):
    """Validate and save edits to a draft proposal."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)

    try:
        draft = validate_draft(_proposal_form(request.form))
    except ValueError as exc:
        return json(
            {"detail": str(exc), **({"field": exc.field} if isinstance(exc, FieldValidationError) else {})}, status=400
        )
    async with session_scope() as db:
        proposal = await db.scalar(select(BouquetProposal).where(BouquetProposal.id == proposal_id).with_for_update())
        if not proposal or proposal.status != "draft":
            return json({"detail": "Only drafts can be edited."}, status=409)
        for index, line in enumerate(draft["lines"], start=1):
            if line["listing_id"] and not await db.get(FlowerListing, line["listing_id"]):
                raw_index = (
                    [
                        int(token)
                        for token in str(request.form.get("line_ids", "")).split(",")
                        if token and str(request.form.get(f"name_{token}", "")).strip()
                    ]
                    if request.form.get("line_ids")
                    else None
                )
                return json(
                    {
                        "detail": "A listing reference does not exist.",
                        "field": f"listing_{raw_index[index - 1] if raw_index else index}",
                    },
                    status=400,
                )
        proposal.draft = draft
        proposal.internal_notes = str(request.form.get("internal_notes", "")).strip()[:4000]
        proposal.activity = [
            *(proposal.activity or []),
            dict(action="draft saved", actor=request.ctx.admin.id, at=datetime.now(UTC).isoformat()),
        ]
        await db.commit()
    return redirect(f"/admin/proposals/{proposal_id}")


@bp.post("/proposals/<proposal_id:int>/send")
async def proposal_send(request, proposal_id: int):
    """Send the draft proposal as a Stripe invoice."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)

    try:
        await send_invoice(proposal_id)
    except ValueError as exc:
        return json({"detail": str(exc)}, status=409)
    except Exception:
        return json({"detail": "Invoice outcome is uncertain. Review Stripe before trying again."}, status=503)
    return redirect(f"/admin/proposals/{proposal_id}")


@bp.post("/proposals/<proposal_id:int>/<action:str>")
async def proposal_invoice_action(request, proposal_id: int, action: str):
    """Resend, void or revise a sent proposal invoice."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)

    try:
        await update_sent_invoice(proposal_id, action)
    except ValueError as exc:
        return json({"detail": str(exc)}, status=409)
    except Exception:
        return json({"detail": "Stripe outcome is uncertain; inspect the invoice before retrying."}, status=503)
    return redirect(f"/admin/proposals/{proposal_id}")


@bp.post("/<slug:str>/<pk:int>")
async def model_update(request, slug: str, pk: int):
    """Update a registry model entry from a submitted form."""
    admin = REGISTRY_BY_SLUG.get(slug)
    if admin is None:
        return redirect("/admin/")
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)
    if slug == "inquiries":
        return json({"detail": "Use the inquiry follow-up form to update its stage."}, status=400)
    if slug == "flowers" and (error := _flower_delivery_fee_error(request.form)):
        return json({"detail": error}, status=400)
    if slug == "announcements" and (error := _announcement_error(request.form)):
        return json({"detail": error}, status=400)
    if slug == "gallery" and (error := _gallery_error(request.form)):
        return json({"detail": error}, status=400)
    async with session_scope() as session:
        obj = await session.get(admin.model, pk)
        if obj is None:
            return redirect(f"/admin/{slug}")
        try:
            chosen_image = await _selected_gallery_image(session, request.form, request.files, slug)
            await _apply_form(obj, admin, request.form, request.files)
        except ValueError as exc:
            return json({"detail": str(exc)}, status=400)
        except Exception:
            return json({"detail": "Image storage unavailable; nothing was saved."}, status=503)
        if chosen_image:
            obj.photo = chosen_image.image
        await session.commit()
    return redirect(f"/admin/{slug}")


@bp.post("/<slug:str>/<pk:int>/delete")
async def model_delete(request, slug: str, pk: int):
    """Delete a registry model entry when nothing depends on it."""
    admin = REGISTRY_BY_SLUG.get(slug)
    if admin is None:
        return redirect("/admin/")
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)
    if slug == "orders":
        return json({"detail": "Order history cannot be deleted."}, status=409)
    if slug == "florists":
        return json({"detail": "Use owner-reviewed account suspension/deletion in Account security."}, status=409)
    async with session_scope() as session:
        obj = await session.get(admin.model, pk)
        if obj is None:
            return redirect(f"/admin/{slug}")
        if slug == "flowers":
            has_orders = await session.scalar(select(OrderItem.id).where(OrderItem.listing_id == pk).limit(1))
            has_inventory_history = await session.scalar(
                select(InventoryMovement.id).where(InventoryMovement.listing_id == pk).limit(1)
            )
            if has_orders or has_inventory_history:
                return json(
                    {"detail": "Listings with order or inventory history cannot be deleted."},
                    status=409,
                )
        await session.delete(obj)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return _page(
                request,
                "admin/list.html",
                status=409,
                admin=admin,
                rows=[],
                display=[],
                query="",
                total=0,
                page_number=1,
                pages=1,
                status_filter="",
                error="This entry cannot be deleted because other records depend on it.",
            )
    return redirect(f"/admin/{slug}")


@bp.get("/flowers/<pk:int>/inventory")
async def flower_inventory(request, pk: int):
    """Render or export the stock journal for a listing."""
    if not request.ctx.admin:
        return redirect("/admin/login")

    kind = str(request.args.get("kind", "")).strip()
    query = str(request.args.get("q", "")).strip()[:100]
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        return json({"detail": "Page must be a number."}, status=400)
    page = min(page, 100000)

    async with session_scope() as db:
        listing = await db.get(FlowerListing, pk)
        if not listing:
            return redirect("/admin/flowers")
        reserved = await db.scalar(
            select(func.coalesce(func.sum(OrderItem.quantity), 0))
            .join(Order, Order.id == OrderItem.order_id)
            .where(OrderItem.listing_id == pk, Order.status == "pending")
        )
        filters = [InventoryMovement.listing_id == pk]
        if kind:
            filters.append(InventoryMovement.kind == kind)
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            filters.append(
                or_(
                    InventoryMovement.reason.ilike(pattern, escape="\\"),
                    InventoryMovement.source.ilike(pattern, escape="\\"),
                )
            )
        statement = select(InventoryMovement).where(*filters).order_by(InventoryMovement.id.desc())
        if request.args.get("format") == "csv":
            movements = (await db.scalars(statement)).all()
        else:
            movements = (await db.scalars(statement.limit(100).offset((page - 1) * 100))).all()
        movement_count = await db.scalar(select(func.count()).select_from(InventoryMovement).where(*filters))
    if request.args.get("format") == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            (
                "Movement ID",
                "Date UTC",
                "Listing",
                "Kind",
                "Available change",
                "Units",
                "Order ID",
                "Actor ID",
                "Source",
                "Reason",
            )
        )

        def safe(value):
            value = str(value or "")
            return "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value

        for movement in movements:
            writer.writerow(
                (
                    movement.id,
                    movement.created_at.isoformat(),
                    listing.listing_code,
                    movement.kind,
                    movement.delta,
                    movement.units,
                    movement.order_id or "",
                    movement.actor_id or "",
                    safe(movement.source),
                    safe(movement.reason),
                )
            )
        return text(
            output.getvalue(),
            content_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=inventory-{listing.listing_code}.csv"},
        )
    return _page(
        request,
        "admin/inventory.html",
        listing=listing,
        movements=movements,
        reserved=reserved,
        on_hand=listing.quantity_available + reserved,
        movement_count=movement_count,
        page=page,
        kind=kind,
        query=query,
        movement_params=urlencode({"kind": kind, "q": query}),
    )


@bp.get("/inventory/stock")
async def stock_overview(request):
    """Show availability and pending holds across listings."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    async with session_scope() as db:
        flowers = (await db.scalars(select(FlowerListing).order_by(FlowerListing.name))).all()
        reserved_rows = (
            await db.execute(
                select(OrderItem.listing_id, func.sum(OrderItem.quantity))
                .join(Order, Order.id == OrderItem.order_id)
                .where(Order.status == "pending", OrderItem.listing_id.is_not(None))
                .group_by(OrderItem.listing_id)
            )
        ).all()
    reserved = dict(reserved_rows)
    return _page(request, "admin/stock_overview.html", flowers=flowers, reserved=reserved)


@bp.post("/inventory/bulk-restock")
async def bulk_restock(request):
    """Restock several listings in one transaction."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)

    reason = str(request.form.get("reason", "")).strip()
    source = str(request.form.get("source", "")).strip()
    if not reason or len(reason) > 255 or not source or len(source) > 100:
        return json({"detail": "Enter a harvest source and reason."}, status=400)
    entries = []
    for index in range(1, 11):
        listing_id = str(request.form.get(f"listing_{index}", "")).strip()
        units = str(request.form.get(f"units_{index}", "")).strip()
        if not listing_id and not units:
            continue
        if not listing_id.isdigit() or not units.isdigit() or not 1 <= int(units) <= 999999:
            return json({"detail": "Choose a listing and positive whole-number quantity for each line."}, status=400)
        entries.append((int(listing_id), int(units)))
    if not entries:
        return json({"detail": "Add at least one listing to restock."}, status=400)
    combined: dict[int, int] = {}
    for listing_id, units in entries:
        combined[listing_id] = combined.get(listing_id, 0) + units
        if combined[listing_id] > 999999:
            return json({"detail": "Too many units for one listing."}, status=400)
    async with session_scope() as db:
        for listing_id, units in sorted(combined.items()):
            flower = await db.scalar(select(FlowerListing).where(FlowerListing.id == listing_id).with_for_update())
            if not flower:
                return json({"detail": "Listing not found; no stock was changed."}, status=404)
            await change_stock(
                db,
                flower,
                units,
                kind="restock",
                units=units,
                actor_id=request.ctx.admin.id,
                reason=reason,
                source=source,
            )
        await db.commit()
    return redirect("/admin/inventory/stock")


@bp.post("/flowers/<pk:int>/duplicate")
async def duplicate_flower(request, pk: int):
    """Create an inactive copy of a listing without copying its stock."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)

    async with session_scope() as db:
        original = await db.get(FlowerListing, pk)
        if not original:
            return json({"detail": "Listing not found."}, status=404)
        duplicate = FlowerListing(
            name=f"{original.name} (copy)"[:160],
            variety=original.variety,
            color=original.color,
            photo=original.photo,
            stem_notes=original.stem_notes,
            price=original.price,
            delivery_fee=original.delivery_fee,
            delivery_fee_mode=original.delivery_fee_mode,
            unit=original.unit,
            quantity_available=0,
            sold_out=original.sold_out,
            channel=original.channel,
            season=original.season,
            active=False,
            sort_order=original.sort_order,
            low_stock_threshold=original.low_stock_threshold,
        )
        db.add(duplicate)
        await db.flush()
        await change_stock(
            db,
            duplicate,
            0,
            kind="opening",
            units=0,
            actor_id=request.ctx.admin.id,
            source="duplicate",
            reason=f"Duplicated from {original.listing_code}; stock not copied",
        )
        await db.commit()
    return redirect(f"/admin/flowers/{duplicate.id}")


@bp.post("/flowers/bulk-update")
async def bulk_update_flowers(request):
    """Apply one field change to several listings."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)
    raw_ids = str(request.form.get("listing_ids", ""))
    try:
        ids = sorted({int(value.strip()) for value in raw_ids.split(",")})
    except ValueError:
        return json({"detail": "Enter comma-separated listing IDs."}, status=400)
    if not ids or len(ids) > 100 or any(value < 1 for value in ids):
        return json({"detail": "Choose 1–100 valid listing IDs."}, status=400)
    action = str(request.form.get("action", ""))
    value = str(request.form.get("value", "")).strip()
    if action == "active" and value not in ("true", "false"):
        return json({"detail": "Choose active or inactive."}, status=400)
    if action == "channel" and value not in ("retail", "wholesale", "both"):
        return json({"detail": "Choose a valid channel."}, status=400)
    if action == "season" and value not in ("spring", "summer", "fall", "winter", "year_round", ""):
        return json({"detail": "Choose a valid season."}, status=400)
    if action == "price":
        try:
            value = _money(value)
        except ValueError as exc:
            return json({"detail": str(exc)}, status=400)
    elif action not in ("active", "channel", "season"):
        return json({"detail": "Choose an allowed bulk update."}, status=400)
    async with session_scope() as db:
        rows = (
            await db.scalars(
                select(FlowerListing).where(FlowerListing.id.in_(ids)).order_by(FlowerListing.id).with_for_update()
            )
        ).all()
        if len(rows) != len(ids):
            return json({"detail": "Some listings no longer exist; nothing was updated."}, status=404)
        for flower in rows:
            setattr(flower, action, value == "true" if action == "active" else value)
        await db.commit()
    return redirect("/admin/flowers")


@bp.post("/flowers/<pk:int>/adjust")
async def flower_adjust(request, pk: int):
    """Record a manual stock adjustment for a listing."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)

    kind = request.form.get("kind")
    reason = str(request.form.get("reason", "")).strip()
    try:
        quantity = int(request.form.get("quantity", ""))
    except ValueError, TypeError:
        return json({"detail": "Enter a whole-number quantity."}, status=400)
    if (
        kind not in ("restock", "waste", "market_sale", "adjustment")
        or not reason
        or abs(quantity) > 999999
        or quantity == 0
    ):
        return json({"detail": "Choose an action, nonzero quantity and reason."}, status=400)
    if kind != "adjustment" and quantity < 0:
        return json({"detail": "Use a positive quantity for this action."}, status=400)
    delta = quantity if kind in ("restock", "adjustment") else -quantity
    try:
        async with session_scope() as db:
            listing = await db.scalar(select(FlowerListing).where(FlowerListing.id == pk).with_for_update())
            if not listing:
                return json({"detail": "Listing not found."}, status=404)
            await change_stock(
                db,
                listing,
                delta,
                kind=kind,
                units=abs(quantity),
                actor_id=request.ctx.admin.id,
                reason=reason,
                source="admin",
            )
            await db.commit()
    except StockError as exc:
        return json({"detail": str(exc)}, status=409)
    return redirect(f"/admin/flowers/{pk}/inventory")


@bp.post("/flowers/<pk:int>/count")
async def flower_count(request, pk: int):
    """Record a physical count as a stock movement."""
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)

    try:
        counted = int(str(request.form.get("on_hand", "")))
    except ValueError:
        return json({"detail": "Enter a whole-number physical count."}, status=400)
    reason = str(request.form.get("reason", "")).strip()
    if counted < 0 or counted > 999999 or not reason or len(reason) > 255:
        return json({"detail": "Enter a nonnegative count and a reason."}, status=400)
    async with session_scope() as db:
        listing = await db.scalar(select(FlowerListing).where(FlowerListing.id == pk).with_for_update())
        if not listing:
            return json({"detail": "Listing not found."}, status=404)
        reserved = await db.scalar(
            select(func.coalesce(func.sum(OrderItem.quantity), 0))
            .join(Order, Order.id == OrderItem.order_id)
            .where(OrderItem.listing_id == pk, Order.status == "pending")
        )
        if counted < reserved:
            return json(
                {"detail": f"Count cannot be less than {reserved} reserved units. Resolve held orders first."},
                status=409,
            )
        delta = counted - reserved - listing.quantity_available
        await change_stock(
            db,
            listing,
            delta,
            kind="count",
            units=max(1, abs(delta)),
            actor_id=request.ctx.admin.id,
            reason=reason,
            source="physical_count",
        )
        await db.commit()
    return redirect(f"/admin/flowers/{pk}/inventory")


@bp.post("/<slug:str>/<pk:int>/action/<action:str>")
async def model_action(request, slug: str, pk: int, action: str):
    """Run a registry model action such as approving a florist."""
    admin = REGISTRY_BY_SLUG.get(slug)
    if admin is None or action not in admin.actions:
        return redirect("/admin/")
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)

    if slug == "orders":
        if action == "cancel":
            result = await expire_checkout(pk)
            if result == "review":
                return json({"detail": "Stripe payment needs review; stock was not released."}, status=409)
        async with session_scope() as session:
            order = await load_order(session, pk, for_update=True)
            if order is None:
                return json({"detail": "Order not found."}, status=404)
            if action == "cancel" and order.status == "pending":
                await release_order(session, order)
                order.status = "cancelled"
            elif action == "fulfill" and order.status == "paid" and not order.fulfilled_at:
                order.fulfilled_at = datetime.now(UTC)
                order.fulfillment_state = "completed"
                order.activity = [
                    *(order.activity or []),
                    dict(action="completed", actor=request.ctx.admin.id, at=order.fulfilled_at.isoformat()),
                ]
            elif action == "restock" and order.status == "refunded" and not order.restocked_at:
                already = await session.scalar(
                    select(InventoryMovement.id)
                    .where(InventoryMovement.order_id == pk, InventoryMovement.kind == "return")
                    .limit(1)
                )
                if already:
                    return json({"detail": "Order has already been restocked."}, status=409)

                for item in sorted(
                    (item for item in order.items if item.listing_id is not None), key=lambda item: item.listing_id
                ):
                    listing = await session.scalar(
                        select(FlowerListing).where(FlowerListing.id == item.listing_id).with_for_update()
                    )
                    await change_stock(
                        session,
                        listing,
                        item.quantity,
                        kind="return",
                        units=item.quantity,
                        order_id=pk,
                        actor_id=request.ctx.admin.id,
                        reason="Operator confirmed refunded goods returned to stock",
                        source="admin",
                    )
                order.restocked_at = datetime.now(UTC)
            else:
                return json({"detail": "This action is not valid for the order's state."}, status=409)
            await session.commit()
    elif slug == "florists" and action == "approve":
        async with session_scope() as session:
            profile = await session.scalar(
                select(FloristProfile).options(selectinload(FloristProfile.user)).where(FloristProfile.id == pk)
            )
            if profile is not None and not profile.approved:
                profile.approved = True
                email = profile.user.email
                await session.commit()
                send_wholesale_approval_email(email=email)

    return redirect(f"/admin/{slug}")
