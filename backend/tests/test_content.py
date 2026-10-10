import pytest

from app.db import session_scope
from app.models import Announcement, GalleryImage
from app.server import app


@pytest.mark.asyncio
async def test_announcement_returns_null_when_none_active():
    async with session_scope() as session:
        session.add(Announcement(text="Hidden", active=False))
        await session.commit()

    _, response = await app.asgi_client.get("/api/announcement/")

    assert response.status == 200
    assert response.json == {"announcement": None}


@pytest.mark.asyncio
async def test_announcement_returns_the_most_recent_active():
    async with session_scope() as session:
        session.add(Announcement(text="Older", active=True))
        await session.commit()
    async with session_scope() as session:
        session.add(
            Announcement(
                text="Spring flowers are here",
                link_url="https://example.com/shop",
                link_label="Shop now",
                active=True,
            )
        )
        await session.commit()

    _, response = await app.asgi_client.get("/api/announcement/")

    assert response.status == 200
    payload = response.json["announcement"]
    assert payload["text"] == "Spring flowers are here"
    assert payload["link_label"] == "Shop now"


@pytest.mark.asyncio
async def test_gallery_lists_only_active_images_in_sort_order():
    async with session_scope() as session:
        session.add_all(
            [
                GalleryImage(image="gallery/b.jpg", caption="Second", sort_order=2, active=True),
                GalleryImage(image="gallery/a.jpg", caption="First", sort_order=1, active=True),
                GalleryImage(image="gallery/c.jpg", caption="Hidden", sort_order=0, active=False),
            ]
        )
        await session.commit()

    _, response = await app.asgi_client.get("/api/gallery/")

    assert response.status == 200
    assert [item["caption"] for item in response.json] == ["First", "Second"]
    assert response.json[0]["image"].endswith("/media/gallery/a.jpg")
