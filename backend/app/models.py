"""SQLAlchemy models for the Honey Summer schema.

Typed SQLAlchemy 2.0 models with clean table names; Alembic owns the schema.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    profile: Mapped[Optional["FloristProfile"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    orders: Mapped[list["Order"]] = relationship(back_populates="customer")

    def __str__(self) -> str:
        return self.email


class FloristProfile(Base):
    __tablename__ = "florist_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    business_name: Mapped[str] = mapped_column(String(200))
    contact_name: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    business_type: Mapped[str] = mapped_column(String(30), default="")
    website: Mapped[str] = mapped_column(String(500), default="")
    about_work: Mapped[str] = mapped_column(Text, default="")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")

    user: Mapped[User] = relationship(back_populates="profile")

    def __str__(self) -> str:
        return self.business_name


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(String(200))
    link_url: Mapped[str] = mapped_column(String(500), default="")
    link_label: Mapped[str] = mapped_column(String(80), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    def __str__(self) -> str:
        return self.text


class GalleryImage(Base):
    __tablename__ = "gallery_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    image: Mapped[str] = mapped_column(String(255))
    alt_text: Mapped[str] = mapped_column(String(250), default="")
    caption: Mapped[str] = mapped_column(String(250), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def __str__(self) -> str:
        return self.caption or self.alt_text or f"Gallery image {self.id}"


class Inquiry(Base):
    __tablename__ = "inquiries"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(254))
    phone: Mapped[str] = mapped_column(String(40), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    photo: Mapped[str] = mapped_column(String(255), default="")
    handled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def __str__(self) -> str:
        return f"{self.kind} — {self.name}"


class FlowerListing(Base):
    __tablename__ = "flower_listings"
    __table_args__ = (
        CheckConstraint("delivery_fee >= 0", name="flower_delivery_fee_nonnegative"),
        CheckConstraint("quantity_available >= 0", name="flower_available_nonnegative"),
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
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def available(self) -> bool:
        return self.active and not self.sold_out and self.quantity_available > 0

    @property
    def listing_code(self) -> str:
        return f"FL-{self.id:04d}"

    def __str__(self) -> str:
        return self.name


class InventoryMovement(Base):
    """Append-only available-stock journal. Zero-delta sale entries close holds."""

    __tablename__ = "inventory_movements"
    __table_args__ = (CheckConstraint("units > 0 OR kind = 'opening'", name="movement_units_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("flower_listings.id"), index=True)
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"), nullable=True, index=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))
    delta: Mapped[int] = mapped_column(Integer)
    units: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Wholesale orders reference the approved florist account. Retail orders
    # are guest checkouts, so the customer FK is optional and the contact
    # details below carry the buyer instead.
    customer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    customer_name: Mapped[str] = mapped_column(String(200), default="")
    customer_email: Mapped[str] = mapped_column(String(254), default="")
    customer_phone: Mapped[str] = mapped_column(String(40), default="")
    channel: Mapped[str] = mapped_column(String(10), default="wholesale")
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0)
    fulfillment: Mapped[str] = mapped_column(String(10), default="pickup")
    pickup_window: Mapped[str] = mapped_column(String(200), default="")
    delivery_address: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    stripe_session_id: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, nullable=True
    )
    status: Mapped[str] = mapped_column(String(12), default="pending")
    hold_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    fulfilled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    restocked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    stripe_payment_intent_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    customer: Mapped[Optional[User]] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )

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
        return f"HS{self.id:06d}"

    def __str__(self) -> str:
        return f"Order #{self.id}"


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    listing_id: Mapped[int] = mapped_column(ForeignKey("flower_listings.id"))
    name_snapshot: Mapped[str] = mapped_column(String(160))
    price_snapshot: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    quantity: Mapped[int] = mapped_column(Integer)

    order: Mapped[Order] = relationship(back_populates="items")
    listing: Mapped[FlowerListing] = relationship()


class StripeEvent(Base):
    __tablename__ = "stripe_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(255), unique=True)
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrderNotification(Base):
    __tablename__ = "order_notifications"
    __table_args__ = (UniqueConstraint("order_id", "recipient", name="uq_order_notification_recipient"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    recipient: Mapped[str] = mapped_column(String(10))
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
