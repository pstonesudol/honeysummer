"""Public read endpoints: the announcement banner and the wedding gallery."""

from sanic import Blueprint
from sanic.response import json
from sqlalchemy import select

from ..db import session_scope
from ..models import Announcement, GalleryImage
from ..schemas import AnnouncementOut, GalleryImageOut
from ..settings import get_settings

bp = Blueprint("content", url_prefix="/api")


def _gallery_payload(image: GalleryImage) -> dict:
    base = get_settings().media_url.rstrip("/")
    return {
        **GalleryImageOut.model_validate(image).model_dump(),
        "image": f"{base}/{image.image}" if image.image else "",
    }


@bp.get("/announcement/")
async def announcement(request):
    async with session_scope() as session:
        result = await session.execute(
            select(Announcement)
            .where(Announcement.active.is_(True))
            .order_by(Announcement.created_at.desc())
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
