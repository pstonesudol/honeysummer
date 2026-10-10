"""Public read endpoints: the announcement banner and the wedding gallery."""

from sanic import Blueprint
from sanic.response import json
from sqlalchemy import or_, select
from datetime import datetime
from zoneinfo import ZoneInfo

from ..db import session_scope
from ..models import Announcement, GalleryImage, SiteContent
from ..schemas import AnnouncementOut, GalleryImageOut
from ..media import public_media_url

bp = Blueprint("content", url_prefix="/api")


@bp.get("/site-content/")
async def site_content(request):
    async with session_scope() as session:
        settings = await session.get(SiteContent, 1)
    return json({"content": settings.content if settings else {}})


def _gallery_payload(image: GalleryImage) -> dict:
    base = public_media_url()
    return {
        **GalleryImageOut.model_validate(image).model_dump(),
        "image": f"{base}/{image.image}" if image.image else "",
    }


@bp.get("/announcement/")
async def announcement(request):
    today = datetime.now(ZoneInfo("America/New_York")).date()
    async with session_scope() as session:
        result = await session.execute(
            select(Announcement)
            .where(Announcement.active.is_(True),
                   or_(Announcement.starts_on.is_(None), Announcement.starts_on <= today),
                   or_(Announcement.ends_on.is_(None), Announcement.ends_on >= today))
            .order_by(Announcement.starts_on.desc(), Announcement.created_at.desc())
            .limit(1)
        )
        current = result.scalar_one_or_none()
    payload = AnnouncementOut.model_validate(current).model_dump() if current else None
    return json({"announcement": payload})


@bp.get("/gallery/")
async def gallery(request):
    async with session_scope() as session:
        result = await session.execute(
            select(GalleryImage)
            .where(GalleryImage.active.is_(True))
            .order_by(GalleryImage.sort_order, GalleryImage.id)
        )
        images = result.scalars().all()
    return json([_gallery_payload(image) for image in images])
