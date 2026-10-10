"""SQLAlchemy models for the Honey Summer schema.

Typed SQLAlchemy 2.0 models with clean table names; Alembic owns the schema.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def initial_account_role(context) -> str:
    """Preserve trusted legacy operator creation; invitations explicitly set staff."""
    return "owner" if context.get_current_parameters().get("is_admin") else "florist"


class User(Base):
    """A registered account, either a shop operator or a wholesale florist."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[str] = mapped_column(String(20), default=initial_account_role)
    security_version: Mapped[int] = mapped_column(Integer, default=0)
    mfa_secret: Mapped[str] = mapped_column(Text, default="")
    mfa_pending: Mapped[str] = mapped_column(Text, default="")
    mfa_last_step: Mapped[int] = mapped_column(Integer, default=0)
    recovery_codes: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    profile: Mapped[FloristProfile | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    orders: Mapped[list[Order]] = relationship(back_populates="customer")

    def __str__(self) -> str:
        """Return the account email for admin display."""
        return self.email


class FloristProfile(Base):
    """Wholesale florist business details and approval state."""

    __tablename__ = "florist_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    business_name: Mapped[str] = mapped_column(String(200))
    contact_name: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    business_type: Mapped[str] = mapped_column(String(30), default="")
    website: Mapped[str] = mapped_column(String(500), default="")
    about_work: Mapped[str] = mapped_column(Text, default="")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    application_state: Mapped[str] = mapped_column(String(20), default="pending")
    decision_reason: Mapped[str] = mapped_column(Text, default="")

    user: Mapped[User] = relationship(back_populates="profile")

    def __str__(self) -> str:
        """Return the business name for admin display."""
        return self.business_name


class Announcement(Base):
    """A dated storefront announcement banner."""

    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(String(200))
    link_url: Mapped[str] = mapped_column(String(500), default="")
    link_label: Mapped[str] = mapped_column(String(80), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    starts_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    def __str__(self) -> str:
        """Return the announcement text for admin display."""
        return self.text


class GalleryImage(Base):
    """A storefront gallery photo with alt text and a focal point."""

    __tablename__ = "gallery_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    image: Mapped[str] = mapped_column(String(255))
    alt_text: Mapped[str] = mapped_column(String(250), default="")
    caption: Mapped[str] = mapped_column(String(250), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    focal_x: Mapped[int] = mapped_column(Integer, default=50)
    focal_y: Mapped[int] = mapped_column(Integer, default=50)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def __str__(self) -> str:
        """Return a caption, alt text or fallback label for the image."""
        return self.caption or self.alt_text or f"Gallery image {self.id}"


class SiteContent(Base):
    """Single owner-edited storefront content document."""

    __tablename__ = "site_content"

    id: Mapped[int] = mapped_column(primary_key=True)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AdminActivity(Base):
    """Append-only administrative request outcomes; never stores form secrets."""

    __tablename__ = "admin_activity"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    path: Mapped[str] = mapped_column(String(500))
    status_code: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Inquiry(Base):
    """A customer inquiry submitted from the public site."""

    __tablename__ = "inquiries"
    __table_args__ = (
        CheckConstraint("stage IN ('new', 'contacted', 'quoted', 'booked', 'closed')", name="inquiry_stage_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(254))
    phone: Mapped[str] = mapped_column(String(40), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    photo: Mapped[str] = mapped_column(String(255), default="")
    email_delivery: Mapped[dict] = mapped_column(JSON, default=dict)
    handled: Mapped[bool] = mapped_column(Boolean, default=False)
    stage: Mapped[str] = mapped_column(String(20), default="new")
    follow_up_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    internal_notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def __str__(self) -> str:
        """Return the inquiry kind and customer name for admin display."""
        return f"{self.kind} — {self.name}"


class InquiryCorrespondence(Base):
    """Owner-entered record of a conversation; this does not send email."""

    __tablename__ = "inquiry_correspondence"
    __table_args__ = (CheckConstraint("direction IN ('received', 'sent')", name="correspondence_direction_valid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    inquiry_id: Mapped[int] = mapped_column(ForeignKey("inquiries.id"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    direction: Mapped[str] = mapped_column(String(12))
    subject: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)


class BouquetProposal(Base):
    """An inquiry's editable draft and immutable sent invoice snapshots."""

    __tablename__ = "bouquet_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    inquiry_id: Mapped[int] = mapped_column(ForeignKey("inquiries.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    draft: Mapped[dict] = mapped_column(JSON, default=dict)
    history: Mapped[list] = mapped_column(JSON, default=list)
    activity: Mapped[list] = mapped_column(JSON, default=list)
    internal_notes: Mapped[str] = mapped_column(Text, default="")
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_invoice_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    invoice_url: Mapped[str] = mapped_column(Text, default="")
    invoice_number: Mapped[str] = mapped_column(String(100), default="")
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WeddingQuote(Base):
    """An event quote; deposits book work, full payment creates the order."""

    __tablename__ = "wedding_quotes"

    id: Mapped[int] = mapped_column(primary_key=True)
    inquiry_id: Mapped[int] = mapped_column(ForeignKey("inquiries.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    draft: Mapped[dict] = mapped_column(JSON, default=dict)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    payment_mode: Mapped[str] = mapped_column(String(20), default="full")
    deposit_cents: Mapped[int] = mapped_column(Integer, default=0)
    installments: Mapped[list] = mapped_column(JSON, default=list)
    amendments: Mapped[list] = mapped_column(JSON, default=list)
    amendment_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    initial_send_mode: Mapped[str] = mapped_column(String(12), default="manual")
    initial_send_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    initial_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    balance_send_mode: Mapped[str] = mapped_column(String(12), default="manual")
    balance_send_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    balance_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), unique=True, nullable=True)
    activity: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WeddingInvoice(Base):
    """One Stripe invoice issued for a wedding quote payment step."""

    __tablename__ = "wedding_invoices"
    __table_args__ = (UniqueConstraint("quote_id", "step", "revision", name="uq_wedding_invoice_revision"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("wedding_quotes.id"), index=True)
    step: Mapped[str] = mapped_column(String(10))  # full | deposit | balance
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="issuing")
    amount_cents: Mapped[int] = mapped_column(Integer)
    stripe_invoice_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    hosted_url: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FlowerListing(Base):
    """A sellable flower or arrangement with pricing and available stock."""

    __tablename__ = "flower_listings"
    __table_args__ = (
        CheckConstraint("delivery_fee >= 0", name="flower_delivery_fee_nonnegative"),
        CheckConstraint("quantity_available >= 0", name="flower_available_nonnegative"),
        CheckConstraint("low_stock_threshold >= 0", name="flower_low_stock_threshold_nonnegative"),
        CheckConstraint(
            "delivery_fee_mode IN ('per_listing', 'per_unit', 'per_order')",
            name="flower_delivery_fee_mode_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    variety: Mapped[str] = mapped_column(String(160), default="")
    color: Mapped[str] = mapped_column(String(100), default="")
    photo: Mapped[str] = mapped_column(String(255), default="")
    stem_notes: Mapped[str] = mapped_column(String(250), default="")
    price: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0)
    delivery_fee_mode: Mapped[str] = mapped_column(String(20), default="per_listing")
    unit: Mapped[str] = mapped_column(String(10), default="stem")
    quantity_available: Mapped[int] = mapped_column(Integer, default=0)
    sold_out: Mapped[bool] = mapped_column(Boolean, default=False)
    channel: Mapped[str] = mapped_column(String(10), default="wholesale")
    season: Mapped[str] = mapped_column(String(20), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    low_stock_threshold: Mapped[int] = mapped_column(Integer, default=5)

    @property
    def available(self) -> bool:
        """Whether the listing is active, in stock and not sold out."""
        return self.active and not self.sold_out and self.quantity_available > 0

    @property
    def listing_code(self) -> str:
        """Return the stable admin reference for this listing."""
        return f"FL-{self.id:04d}"

    def __str__(self) -> str:
        """Return the listing name for admin display."""
        return self.name


class InventoryMovement(Base):
    """Append-only available-stock journal. Zero-delta sale entries close holds."""

    __tablename__ = "inventory_movements"
    __table_args__ = (CheckConstraint("units > 0 OR kind = 'opening'", name="movement_units_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("flower_listings.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True, index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))
    delta: Mapped[int] = mapped_column(Integer)
    units: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Order(Base):
    """A wholesale or retail order with its payment and fulfillment state."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            "fulfillment_state IN ('new', 'preparing', 'ready', 'completed')", name="order_fulfillment_state_valid"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Wholesale orders reference the approved florist account. Retail orders
    # are guest checkouts, so the customer FK is optional and the contact
    # details below carry the buyer instead.
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    customer_name: Mapped[str] = mapped_column(String(200), default="")
    customer_email: Mapped[str] = mapped_column(String(254), default="")
    customer_phone: Mapped[str] = mapped_column(String(40), default="")
    channel: Mapped[str] = mapped_column(String(10), default="wholesale")
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0)
    fulfillment: Mapped[str] = mapped_column(String(10), default="pickup")
    pickup_window: Mapped[str] = mapped_column(String(200), default="")
    delivery_address: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    internal_notes: Mapped[str] = mapped_column(Text, default="")
    fulfillment_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    fulfillment_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    fulfillment_state: Mapped[str] = mapped_column(String(20), default="new")
    activity: Mapped[list] = mapped_column(JSON, default=list)
    payment_method: Mapped[str] = mapped_column(String(20), default="stripe_checkout")
    payment_reference: Mapped[str] = mapped_column(String(255), default="")
    manual_key: Mapped[str | None] = mapped_column(String(36), unique=True, nullable=True)
    checkout_key: Mapped[str | None] = mapped_column(String(36), unique=True, index=True, nullable=True)
    checkout_url: Mapped[str] = mapped_column(Text, default="")
    stripe_session_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    restocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    customer: Mapped[User | None] = relationship(back_populates="orders")
    items: Mapped[list[OrderItem]] = relationship(back_populates="order", cascade="all, delete-orphan")

    @property
    def customer_label(self) -> str:
        """A human name for the buyer, wholesale account or retail guest."""
        if self.customer is not None:
            profile = self.customer.profile
            if profile is not None:
                return f"{profile.business_name} ({self.customer.email})"
            return self.customer.email
        return self.customer_name or self.customer_email or "Guest"

    @property
    def order_reference(self) -> str:
        """Return the customer-facing order reference."""
        return f"HS{self.id:06d}"

    def __str__(self) -> str:
        """Return the order number for admin display."""
        return f"Order #{self.id}"


class OrderItem(Base):
    """A single order line, snapshotting the listing name and price."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    listing_id: Mapped[int | None] = mapped_column(ForeignKey("flower_listings.id"), nullable=True)
    name_snapshot: Mapped[str] = mapped_column(String(160))
    price_snapshot: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    quantity: Mapped[int] = mapped_column(Integer)

    order: Mapped[Order] = relationship(back_populates="items")
    listing: Mapped[FlowerListing | None] = relationship()


class OrderRefund(Base):
    """Payment-only refund journal; a return of goods is a separate movement."""

    __tablename__ = "order_refunds"
    __table_args__ = (CheckConstraint("amount_cents > 0", name="order_refund_amount_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))  # issuing | succeeded | review
    reference: Mapped[str] = mapped_column(String(255), default="")
    reason: Mapped[str] = mapped_column(String(255))
    idempotency_key: Mapped[str] = mapped_column(String(36), unique=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InvoiceRefund(Base):
    """A refund of one verified Stripe invoice payment, not of a quote total."""

    __tablename__ = "invoice_refunds"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="invoice_refund_amount_positive"),
        CheckConstraint("(wedding_invoice_id IS NULL) != (proposal_id IS NULL)", name="invoice_refund_single_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    wedding_invoice_id: Mapped[int | None] = mapped_column(ForeignKey("wedding_invoices.id"), nullable=True, index=True)
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("bouquet_proposals.id"), nullable=True, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    payment_intent_id: Mapped[str] = mapped_column(String(255))
    stripe_refund_id: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20))  # issuing | succeeded | review
    reason: Mapped[str] = mapped_column(String(255))
    idempotency_key: Mapped[str] = mapped_column(String(36), unique=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReconciliationRun(Base):
    """Durable operator visibility for scheduled Stripe/stock checks."""

    __tablename__ = "reconciliation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    full: Mapped[bool] = mapped_column(Boolean, default=False)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    finding_count: Mapped[int] = mapped_column(Integer, default=0)


class StripeEvent(Base):
    """A processed Stripe webhook event, recorded to prevent replay."""

    __tablename__ = "stripe_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(255), unique=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrderNotification(Base):
    """An outbox record tracking confirmation-email delivery per recipient."""

    __tablename__ = "order_notifications"
    __table_args__ = (UniqueConstraint("order_id", "recipient", name="uq_order_notification_recipient"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    recipient: Mapped[str] = mapped_column(String(10))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
