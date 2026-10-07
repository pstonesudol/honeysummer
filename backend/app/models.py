"""SQLAlchemy models for the fresh Honey Summer schema.

Typed SQLAlchemy 2.0 models. Table names are clean (no Django ``core_`` /
``auth_`` prefixes); Alembic owns the schema. Until the phase 4g cutover these
collections live alongside the Django tables in the same database.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
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
    phone: Mapped[str] = mapped_column(String(40), default="")
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

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    variety: Mapped[str] = mapped_column(String(160), default="")
    color: Mapped[str] = mapped_column(String(100), default="")
    photo: Mapped[str] = mapped_column(String(255), default="")
    stem_notes: Mapped[str] = mapped_column(String(250), default="")
    price: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    unit: Mapped[str] = mapped_column(String(10), default="stem")
    quantity_available: Mapped[int] = mapped_column(Integer, default=0)
    sold_out: Mapped[bool] = mapped_column(Boolean, default=False)
    channel: Mapped[str] = mapped_column(String(10), default="wholesale")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def available(self) -> bool:
        return self.active and not self.sold_out and self.quantity_available > 0

    def __str__(self) -> str:
        return self.name


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0)
    fulfillment: Mapped[str] = mapped_column(String(10), default="pickup")
    pickup_window: Mapped[str] = mapped_column(String(200), default="")
    delivery_address: Mapped[str] = mapped_column(Text, default="")
    stripe_session_id: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, nullable=True
    )
    status: Mapped[str] = mapped_column(String(12), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    customer: Mapped[User] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )

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
