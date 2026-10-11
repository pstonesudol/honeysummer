"""Recent Instagram media for the storefront's follow-along gallery.

The site reads the account's latest posts through the Instagram API with
Instagram Login (``graph.instagram.com``). A long-lived access token lives in
settings; results are cached in-process so the storefront stays within the
API's hourly call limit, and any failure degrades to the last good (or empty)
list so a temporary Instagram or network problem never breaks a page render.
"""

from __future__ import annotations

import logging
import time

import httpx

from .settings import Settings, get_settings

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.instagram.com"
MEDIA_FIELDS = "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp"
PERMALINK_PREFIX = "https://www.instagram.com/"
CACHE_TTL_SECONDS = 900
MAX_POSTS = 9

# One cached list for the whole process; a single storefront account means keying
# by account would add complexity without buying anything.
_cache: dict[str, tuple[float, list[dict]]] = {}


def reset_cache() -> None:
    """Clear the cached feed (used by tests and after a token change)."""
    _cache.clear()


async def fetch_recent_posts(limit: int = MAX_POSTS) -> list[dict]:
    """Return the account's most recent posts, or an empty list if unavailable."""
    settings = get_settings()
    if not settings.instagram_access_token:
        return []
    limit = max(1, min(limit, MAX_POSTS))
    cached = _cache.get("posts")
    now = time.monotonic()
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1][:limit]
    try:
        payload = await _fetch_media(settings, limit)
    except Exception:  # defensive: a transient API or network error must not break the page
        logger.exception("Unable to load the Instagram feed")
        return cached[1][:limit] if cached else []
    posts = _normalize(payload, limit)
    _cache["posts"] = (now, posts)
    return posts[:limit]


async def _fetch_media(settings: Settings, limit: int) -> dict:
    """Call the Instagram media endpoint with the configured access token."""
    url = f"{GRAPH_BASE_URL}/{settings.instagram_api_version}/me/media"
    params = {"fields": MEDIA_FIELDS, "access_token": settings.instagram_access_token, "limit": limit}
    async with httpx.AsyncClient(timeout=6) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()


def _normalize(payload: dict, limit: int) -> list[dict]:
    """Shape API media items into the small payload the storefront renders."""
    posts = []
    for item in payload.get("data", []):
        media_type = item.get("media_type", "IMAGE")
        image = item.get("thumbnail_url") if media_type == "VIDEO" else item.get("media_url")
        image = image or item.get("media_url") or item.get("thumbnail_url") or ""
        permalink = item.get("permalink", "")
        if not image or not permalink.startswith(PERMALINK_PREFIX):
            continue
        # Instagram media URLs are signed CDN links that rotate, so they are
        # cached only briefly and always re-fetched rather than stored.
        posts.append(
            {
                "id": str(item.get("id", "")),
                "image": image,
                "permalink": permalink,
                "caption": " ".join((item.get("caption") or "").split())[:280],
                "media_type": media_type,
            }
        )
    return posts[:limit]
