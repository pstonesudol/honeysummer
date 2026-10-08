"""Operator admin for Honey Summer, served by the same Sanic process at /admin.

A compact, purpose-built replacement for Django admin: signed-cookie login for
``is_admin`` users, CSRF-protected forms, and generic list/edit views driven by
a small per-model registry.
"""

from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sanic import Blueprint
from sanic.response import html, json, redirect
from sqlalchemy import func, inspect as sa_inspect, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from .auth import verify_password
from .db import session_scope
from .models import (
    Announcement,
    FlowerListing,
    FloristProfile,
    GalleryImage,
    Inquiry,
    InventoryMovement,
    Order,
    OrderItem,
    User,
)
from .settings import BASE_DIR, get_settings

bp = Blueprint("admin", url_prefix="/admin")

ADMIN_COOKIE = "honeysummer_admin"
CSRF_COOKIE = "honeysummer_csrf"
ADMIN_SESSION_MAX_AGE = 60 * 60 * 12  # 12 hours

_env = Environment(
    loader=FileSystemLoader(str(BASE_DIR / "templates")),
    autoescape=select_autoescape(["html"]),
)


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
@dataclass
class Field:
    name: str
    label: str
    kind: str = "text"  # text | textarea | int | decimal | bool | select | file | readonly
    choices: tuple = ()
    readonly: bool = False


@dataclass
class ModelAdmin:
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
            Field("active", "Active", "bool"),
            Field("sort_order", "Sort order", "int"),
        ],
        list_columns=[
            ("Code", "listing_code"),
            ("Name", "name"),
            ("Variety", "variety"),
            ("Channel", "channel"),
            ("Price", "price"),
            ("Qty", "quantity_available"),
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
            _str_field("business_name", "Business name"),
            _str_field("phone", "Phone"),
            Field("approved", "Approved", "bool"),
            Field("notes", "Notes", "textarea"),
        ],
        list_columns=[
            ("Business", "business_name"),
            ("User", "user"),
            ("Approved", "approved"),
            ("Phone", "phone"),
        ],
        order_by=["business_name"],
        search=("business_name",),
        can_create=False,
        actions=("approve",),
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
            Field("handled", "Handled", "bool"),
        ],
        list_columns=[
            ("Kind", "kind"),
            ("Name", "name"),
            ("Email", "email"),
            ("Handled", "handled"),
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
                "status", "Status", "readonly",
            ),
            Field("fulfilled_at", "Fulfilled at", "readonly"),
            Field("restocked_at", "Restocked at", "readonly"),
            Field("fulfillment", "Fulfillment", "readonly"),
            Field("delivery_fee", "Delivery fee", "readonly"),
            Field("pickup_window", "Pickup window", "readonly"),
            Field("delivery_address", "Delivery address", "readonly"),
            Field("notes", "Notes", "readonly"),
            Field("stripe_session_id", "Stripe session", "readonly"),
        ],
        list_columns=[
            ("Order", "order_reference"),
            ("Customer", "customer_label"),
            ("Channel", "channel"),
            ("Status", "status"),
            ("Fulfillment", "fulfillment"),
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


# --------------------------------------------------------------------------- #
# Session + CSRF
# --------------------------------------------------------------------------- #
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="honey-summer-admin")


def create_admin_token(user_id: int) -> str:
    return _serializer().dumps({"uid": user_id})


def read_admin_token(token: str) -> int | None:
    try:
        data = _serializer().loads(token, max_age=ADMIN_SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    uid = data.get("uid") if isinstance(data, dict) else None
    return uid if isinstance(uid, int) else None


async def get_current_admin(request) -> User | None:
    token = request.cookies.get(ADMIN_COOKIE)
    if not token:
        return None
    uid = read_admin_token(token)
    if uid is None:
        return None
    async with session_scope() as session:
        user = await session.get(User, uid)
        if user and user.is_admin and user.is_active:
            return user
    return None


def _valid_csrf(request) -> bool:
    form_token = request.form.get("csrf_token")
    cookie_token = request.cookies.get(CSRF_COOKIE)
    if not form_token or not cookie_token:
        return False
    return secrets.compare_digest(form_token, cookie_token)


@bp.middleware("request")
async def load_admin(request):
    request.ctx.admin = await get_current_admin(request)


def _page(request, template: str, status: int = 200, **context):
    token = secrets.token_urlsafe(32)
    context.setdefault("csrf_token", token)
    context.setdefault("admin", request.ctx.admin)
    context.setdefault("models", REGISTRY)
    context.setdefault("media_url", get_settings().media_url.rstrip("/"))
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
                nested = build(
                    sa_inspect(mapper_class).relationships[name].mapper.class_, child
                )
                loader = loader.options(*nested)
            options.append(loader)
        return options

    return build(model, tree)


def _display_value(obj, path: str) -> str:
    value: Any = obj
    for part in path.split("."):
        value = getattr(value, part, "")
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
    return {"field": field, "value": value, "input_type": input_type, "step": step}


def _save_upload(upload, media_root: Path, subdir: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(upload.name).name) or "upload"
    now = datetime.now(timezone.utc)
    rel_dir = Path(subdir or "uploads") / f"{now:%Y}" / f"{now:%m}"
    dest_dir = media_root / rel_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}_{safe}"
    (dest_dir / filename).write_bytes(upload.body)
    return str(rel_dir / filename)


def _apply_form(obj, admin: ModelAdmin, form, files, media_root: Path) -> None:
    for field in admin.fields:
        if field.readonly:
            continue
        if admin.slug == "flowers" and field.name == "quantity_available" and obj.id is not None:
            continue
        if field.kind == "file":
            upload = files.get(field.name)
            if upload and upload.name:
                setattr(obj, field.name, _save_upload(upload, media_root, admin.subdir))
            continue
        raw = form.get(field.name)
        if field.kind == "bool":
            setattr(obj, field.name, raw in ("on", "true", "1"))
        elif field.kind == "int":
            try:
                setattr(obj, field.name, int(raw or 0))
            except (TypeError, ValueError):
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
    return None


# --------------------------------------------------------------------------- #
# Auth views
# --------------------------------------------------------------------------- #
@bp.get("/login")
async def login_page(request):
    if request.ctx.admin:
        return redirect("/admin/")
    return _page(request, "admin/login.html", error=None)


@bp.post("/login")
async def login_submit(request):
    if not _valid_csrf(request):
        return _page(request, "admin/login.html", status=403, error="Your session expired. Please try again.")
    email = str(request.form.get("email", "")).strip().lower()
    password = str(request.form.get("password", ""))
    async with session_scope() as session:
        user = await session.scalar(select(User).where(User.email == email))
        valid = bool(
            user
            and user.is_admin
            and user.is_active
            and verify_password(user.password_hash, password)
        )
        user_id = user.id if valid else None
    if not valid:
        return _page(request, "admin/login.html", status=400, error="Invalid email or password.")
    response = redirect("/admin/")
    response.add_cookie(
        ADMIN_COOKIE,
        create_admin_token(user_id),
        max_age=ADMIN_SESSION_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=not get_settings().debug,
    )
    return response


@bp.post("/logout")
async def logout(request):
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)
    response = redirect("/admin/login")
    response.delete_cookie(ADMIN_COOKIE)
    return response


# --------------------------------------------------------------------------- #
# Dashboard + CRUD
# --------------------------------------------------------------------------- #
@bp.get("/")
async def dashboard(request):
    if not request.ctx.admin:
        return redirect("/admin/login")
    counts = {}
    async with session_scope() as session:
        for admin in REGISTRY:
            counts[admin.slug] = await session.scalar(
                select(func.count()).select_from(admin.model)
            )
    return _page(request, "admin/dashboard.html", counts=counts)


@bp.get("/<slug:str>")
async def model_list(request, slug: str):
    admin = REGISTRY_BY_SLUG.get(slug)
    if admin is None:
        return redirect("/admin/")
    if not request.ctx.admin:
        return redirect("/admin/login")
    query = request.args.get("q", "").strip()
    async with session_scope() as session:
        statement = select(admin.model).options(
            *_relationship_options(
                admin.model,
                [path for _, path in admin.list_columns] + list(admin.eager),
            )
        )
        if query and admin.search:
            statement = statement.where(
                or_(*[getattr(admin.model, name).ilike(f"%{query}%") for name in admin.search])
            )
        statement = statement.order_by(*_order_columns(admin.model, admin.order_by))
        rows = (await session.execute(statement)).scalars().all()
        display = [
            [(_display_value(row, column), column) for _, column in admin.list_columns]
            for row in rows
        ]
    return _page(
        request,
        "admin/list.html",
        admin=admin,
        rows=rows,
        display=display,
        query=query,
    )


@bp.get("/<slug:str>/new")
async def model_new(request, slug: str):
    admin = REGISTRY_BY_SLUG.get(slug)
    if admin is None or not admin.can_create:
        return redirect("/admin/")
    if not request.ctx.admin:
        return redirect("/admin/login")
    rows = [_field_row(None, f) for f in admin.fields]
    return _page(request, "admin/edit.html", admin=admin, obj=None, rows=rows)


@bp.post("/<slug:str>/new")
async def model_create(request, slug: str):
    admin = REGISTRY_BY_SLUG.get(slug)
    if admin is None or not admin.can_create:
        return redirect("/admin/")
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)
    if slug == "flowers" and (error := _flower_delivery_fee_error(request.form)):
        return json({"detail": error}, status=400)
    async with session_scope() as session:
        obj = admin.model()
        _apply_form(obj, admin, request.form, request.files, get_settings().media_root)
        if slug == "flowers":
            from .orders import change_stock

            initial = obj.quantity_available or 0
            if initial < 0:
                return json({"detail": "Starting quantity cannot be negative."}, status=400)
            obj.quantity_available = 0
            session.add(obj)
            await session.flush()
            await change_stock(
                session, obj, initial, kind="restock" if initial else "opening",
                units=initial, actor_id=request.ctx.admin.id,
                reason="Initial stock", source="admin",
            )
        session.add(obj)
        await session.commit()
    return redirect(f"/admin/{slug}")


@bp.get("/<slug:str>/<pk:int>")
async def model_edit(request, slug: str, pk: int):
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
        obj = await session.scalar(
            select(admin.model).options(*options).where(admin.model.id == pk)
        )
    if obj is None:
        return redirect(f"/admin/{slug}")
    rows = [
        _field_row(obj, Field(f.name, f.label, "readonly") if slug == "flowers" and f.name == "quantity_available" else f)
        for f in admin.fields
    ]
    order_total = None
    if slug == "orders":
        order_total = sum(
            (item.price_snapshot * item.quantity for item in obj.items), Decimal("0")
        ) + obj.delivery_fee
    return _page(
        request, "admin/edit.html", admin=admin, obj=obj, rows=rows,
        order_total=order_total,
    )


@bp.post("/<slug:str>/<pk:int>")
async def model_update(request, slug: str, pk: int):
    admin = REGISTRY_BY_SLUG.get(slug)
    if admin is None:
        return redirect("/admin/")
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)
    if slug == "flowers" and (error := _flower_delivery_fee_error(request.form)):
        return json({"detail": error}, status=400)
    async with session_scope() as session:
        obj = await session.get(admin.model, pk)
        if obj is None:
            return redirect(f"/admin/{slug}")
        _apply_form(obj, admin, request.form, request.files, get_settings().media_root)
        await session.commit()
    return redirect(f"/admin/{slug}")


@bp.post("/<slug:str>/<pk:int>/delete")
async def model_delete(request, slug: str, pk: int):
    admin = REGISTRY_BY_SLUG.get(slug)
    if admin is None:
        return redirect("/admin/")
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)
    if slug == "orders":
        return json({"detail": "Order history cannot be deleted."}, status=409)
    async with session_scope() as session:
        obj = await session.get(admin.model, pk)
        if obj is None:
            return redirect(f"/admin/{slug}")
        if slug == "flowers":
            has_orders = await session.scalar(
                select(OrderItem.id).where(OrderItem.listing_id == pk).limit(1)
            )
            has_inventory_history = await session.scalar(
                select(InventoryMovement.id)
                .where(InventoryMovement.listing_id == pk)
                .limit(1)
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
                error="This entry cannot be deleted because other records depend on it.",
            )
    return redirect(f"/admin/{slug}")


@bp.get("/flowers/<pk:int>/inventory")
async def flower_inventory(request, pk: int):
    if not request.ctx.admin:
        return redirect("/admin/login")
    from .models import InventoryMovement, OrderItem

    async with session_scope() as db:
        listing = await db.get(FlowerListing, pk)
        if not listing:
            return redirect("/admin/flowers")
        reserved = await db.scalar(
            select(func.coalesce(func.sum(OrderItem.quantity), 0))
            .join(Order, Order.id == OrderItem.order_id)
            .where(OrderItem.listing_id == pk, Order.status == "pending")
        )
        movements = (await db.scalars(
            select(InventoryMovement).where(InventoryMovement.listing_id == pk)
            .order_by(InventoryMovement.id.desc()).limit(100)
        )).all()
    return _page(
        request, "admin/inventory.html", listing=listing, movements=movements,
        reserved=reserved, on_hand=listing.quantity_available + reserved,
    )


@bp.post("/flowers/<pk:int>/adjust")
async def flower_adjust(request, pk: int):
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)
    from .orders import StockError, change_stock

    kind = request.form.get("kind")
    reason = str(request.form.get("reason", "")).strip()
    try:
        quantity = int(request.form.get("quantity", ""))
    except (ValueError, TypeError):
        return json({"detail": "Enter a whole-number quantity."}, status=400)
    if kind not in ("restock", "waste", "market_sale", "adjustment") or not reason or abs(quantity) > 999999 or quantity == 0:
        return json({"detail": "Choose an action, nonzero quantity and reason."}, status=400)
    if kind != "adjustment" and quantity < 0:
        return json({"detail": "Use a positive quantity for this action."}, status=400)
    delta = quantity if kind in ("restock", "adjustment") else -quantity
    try:
        async with session_scope() as db:
            listing = await db.scalar(
                select(FlowerListing).where(FlowerListing.id == pk).with_for_update()
            )
            if not listing:
                return json({"detail": "Listing not found."}, status=404)
            await change_stock(
                db, listing, delta, kind=kind, units=abs(quantity),
                actor_id=request.ctx.admin.id, reason=reason, source="admin",
            )
            await db.commit()
    except StockError as exc:
        return json({"detail": str(exc)}, status=409)
    return redirect(f"/admin/flowers/{pk}/inventory")


@bp.post("/<slug:str>/<pk:int>/action/<action:str>")
async def model_action(request, slug: str, pk: int, action: str):
    admin = REGISTRY_BY_SLUG.get(slug)
    if admin is None or action not in admin.actions:
        return redirect("/admin/")
    if not request.ctx.admin:
        return redirect("/admin/login")
    if not _valid_csrf(request):
        return json({"detail": "Invalid CSRF token."}, status=403)

    if slug == "orders":
        from .orders import change_stock, load_order, release_order
        from .models import InventoryMovement
        from .payments import expire_checkout

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
                order.fulfilled_at = datetime.now(timezone.utc)
            elif action == "restock" and order.status == "refunded" and not order.restocked_at:
                already = await session.scalar(
                    select(InventoryMovement.id).where(
                        InventoryMovement.order_id == pk, InventoryMovement.kind == "return"
                    ).limit(1)
                )
                if already:
                    return json({"detail": "Order has already been restocked."}, status=409)
                from .models import FlowerListing
                for item in sorted(order.items, key=lambda item: item.listing_id):
                    listing = await session.scalar(
                        select(FlowerListing).where(FlowerListing.id == item.listing_id).with_for_update()
                    )
                    await change_stock(
                        session, listing, item.quantity, kind="return", units=item.quantity,
                        order_id=pk, actor_id=request.ctx.admin.id,
                        reason="Operator confirmed refunded goods returned to stock", source="admin",
                    )
                order.restocked_at = datetime.now(timezone.utc)
            else:
                return json({"detail": "This action is not valid for the order's state."}, status=409)
            await session.commit()
    elif slug == "florists" and action == "approve":
        from .emails import send_wholesale_approval_email

        async with session_scope() as session:
            profile = await session.scalar(
                select(FloristProfile)
                .options(selectinload(FloristProfile.user))
                .where(FloristProfile.id == pk)
            )
            if profile is not None and not profile.approved:
                profile.approved = True
                email = profile.user.email
                await session.commit()
                send_wholesale_approval_email(email=email)

    return redirect(f"/admin/{slug}")
