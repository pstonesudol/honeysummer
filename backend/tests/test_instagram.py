"""The public Instagram feed endpoint and its normalization rules."""

import pytest

from app import instagram
from app.server import app


@pytest.fixture(autouse=True)
def _clear_cache():
    instagram.reset_cache()
    yield
    instagram.reset_cache()


@pytest.mark.asyncio
async def test_returns_empty_without_a_token(monkeypatch):
    monkeypatch.setattr(instagram.get_settings(), "instagram_access_token", "")
    _, response = await app.asgi_client.get("/api/instagram/")
    assert response.status == 200
    assert response.json == {"posts": []}


@pytest.mark.asyncio
async def test_returns_normalized_recent_posts(monkeypatch):
    monkeypatch.setattr(instagram.get_settings(), "instagram_access_token", "token")

    async def fake_fetch(settings, limit):
        return {
            "data": [
                {
                    "id": "1",
                    "media_type": "IMAGE",
                    "media_url": "https://scontent.example/1.jpg",
                    "permalink": "https://www.instagram.com/p/abc/",
                    "caption": "  Hello   world  ",
                },
                {
                    "id": "2",
                    "media_type": "VIDEO",
                    "media_url": "https://scontent.example/2.mp4",
                    "thumbnail_url": "https://scontent.example/2.jpg",
                    "permalink": "https://www.instagram.com/p/def/",
                },
                {"id": "3", "media_type": "IMAGE", "media_url": "", "permalink": "https://evil.example/p/x/"},
            ]
        }

    monkeypatch.setattr(instagram, "_fetch_media", fake_fetch)
    _, response = await app.asgi_client.get("/api/instagram/")
    assert response.status == 200
    posts = response.json["posts"]
    assert [p["id"] for p in posts] == ["1", "2"]
    assert posts[0]["caption"] == "Hello world"
    assert posts[1]["image"] == "https://scontent.example/2.jpg"


@pytest.mark.asyncio
async def test_failure_degrades_to_empty(monkeypatch):
    monkeypatch.setattr(instagram.get_settings(), "instagram_access_token", "token")

    async def boom(settings, limit):
        raise RuntimeError("nope")

    monkeypatch.setattr(instagram, "_fetch_media", boom)
    _, response = await app.asgi_client.get("/api/instagram/")
    assert response.status == 200
    assert response.json == {"posts": []}
