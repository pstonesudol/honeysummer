"""Pydantic response schemas (serialization layer)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AnnouncementOut(BaseModel):
    """Serialized announcement banner fields for the public API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    text: str
    link_url: str
    link_label: str


class GalleryImageOut(BaseModel):
    """Serialized gallery image fields for the public API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    alt_text: str
    caption: str
    sort_order: int
    focal_x: int
    focal_y: int


class InquiryOut(BaseModel):
    """Serialized inquiry fields returned after submission."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    name: str
    email: str
    phone: str
    message: str
    details: dict
    photo: str
    created_at: datetime
