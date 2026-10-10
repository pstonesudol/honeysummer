"""Approved-florist wholesale catalog."""

from sanic import Blueprint
from sanic.response import json
from sqlalchemy import select

from ..auth import get_current_user
from ..db import session_scope
from ..media import public_media_url
from ..models import FlowerListing

bp = Blueprint("catalog", url_prefix="/api")


def _listing_payload(listing: FlowerListing) -> dict:

    base = public_media_url()
    return {
        "id": listing.id,
        "name": listing.name,
        "variety": listing.variety,
        "color": listing.color,
        "photo_url": f"{base}/{listing.photo}" if listing.photo else "",
        "stem_notes": listing.stem_notes,
        "price": format(listing.price, ".2f"),
        "unit": listing.unit,
        "delivery_fee": format(listing.delivery_fee or 0, ".2f"),
        "delivery_fee_mode": listing.delivery_fee_mode,
        "quantity_available": listing.quantity_available,
        "sold_out": listing.sold_out,
        "available": listing.available,
    }


@bp.get("/flowers/")
async def flowers(request):
    """List wholesale flower listings for an approved florist."""
    user = await get_current_user(request)
    if user is None:
        return json({"detail": "Authentication credentials were not provided."}, status=403)
    profile = user.profile
    if profile is None or not profile.approved:
        return json([])

    async with session_scope() as session:
        result = await session.execute(
            select(FlowerListing)
            .where(
                FlowerListing.active.is_(True),
                FlowerListing.channel.in_(["wholesale", "both"]),
            )
            .order_by(FlowerListing.sort_order, FlowerListing.name, FlowerListing.id)
        )
        listings = result.scalars().all()
    return json([_listing_payload(listing) for listing in listings])
