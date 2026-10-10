from pathlib import Path
from types import SimpleNamespace

import pytest

from app import media


@pytest.mark.asyncio
async def test_gallery_focal_and_listing_photo_reuse(tmp_path, monkeypatch):
    from decimal import Decimal
    from sqlalchemy import select
    from app.admin import CSRF_COOKIE
    from app.auth import hash_password
    from app.db import session_scope
    from app.models import FlowerListing, GalleryImage, User
    from app.server import app
    from app.settings import get_settings
    monkeypatch.setattr(get_settings(), "media_root", tmp_path)
    async with session_scope() as db:
        db.add(User(email="owner@example.com", password_hash=hash_password("password"), is_admin=True))
        db.add(FlowerListing(name="Zinnia", price=Decimal("3.00"), quantity_available=2))
        await db.commit()
    await app.asgi_client.get("/admin/login")
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    await app.asgi_client.post("/admin/login", data=dict(email="owner@example.com", password="password", csrf_token=token))
    await app.asgi_client.get("/admin/gallery/new")
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    _, created = await app.asgi_client.post("/admin/gallery/new", data=dict(
        csrf_token=token, alt_text="Sunlit yellow zinnia", caption="Morning harvest",
        sort_order="1", focal_x="25", focal_y="70", active="on"),
        files={"image": ("sun.png", b"\x89PNG\r\n\x1a\nexample", "image/png")})
    assert created.status == 302
    _, gallery = await app.asgi_client.get("/api/gallery/")
    assert gallery.json[0]["focal_x"] == 25 and gallery.json[0]["focal_y"] == 70
    await app.asgi_client.get("/admin/flowers/1")
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    _, reused = await app.asgi_client.post("/admin/flowers/1", data=dict(
        csrf_token=token, name="Zinnia", price="3.00", gallery_image_id="1"))
    assert reused.status == 302
    async with session_scope() as db:
        listing = await db.get(FlowerListing, 1)
        photo = (await db.scalar(select(GalleryImage.image)))
        assert listing.photo == photo


def test_image_upload_validates_magic_and_stores_local(tmp_path, monkeypatch):
    settings = SimpleNamespace(media_root=tmp_path, media_url="/media", r2_endpoint_url="",
        r2_bucket="", r2_access_key_id="", r2_secret_access_key="", r2_public_url="")
    monkeypatch.setattr(media, "get_settings", lambda: settings)
    with pytest.raises(ValueError, match="PNG"):
        media.store_image(SimpleNamespace(body=b"<svg><script>alert(1)</script></svg>", name="evil.svg"), "gallery")
    with pytest.raises(ValueError, match="8 MB"):
        media.store_image(SimpleNamespace(body=b"\x89PNG\r\n\x1a\n" + b"0" * (8 * 1024 * 1024)), "gallery")
    path = media.store_image(SimpleNamespace(body=b"\x89PNG\r\n\x1a\nimage", name="../unsafe.php"), "gallery")
    assert path.startswith("gallery/") and path.endswith(".png")
    assert (tmp_path / path).read_bytes().startswith(b"\x89PNG")
    assert media.public_media_url() == "/media"


def test_r2_upload_requires_complete_config_and_writes_object(monkeypatch, tmp_path):
    import boto3
    settings = SimpleNamespace(media_root=tmp_path, media_url="/media",
        r2_endpoint_url="https://account.r2.cloudflarestorage.com", r2_bucket="photos",
        r2_access_key_id="test", r2_secret_access_key="secret", r2_public_url="https://images.example.com")
    monkeypatch.setattr(media, "get_settings", lambda: settings)
    uploaded = []
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: SimpleNamespace(
        put_object=lambda **kwargs: uploaded.append(kwargs)))
    key = media.store_image(SimpleNamespace(body=b"\xff\xd8\xfftest", name="photo.jpg"), "flowers")
    assert uploaded[0]["Bucket"] == "photos" and uploaded[0]["ContentType"] == "image/jpeg"
    assert uploaded[0]["Key"] == key and media.public_media_url() == "https://images.example.com"
    assert not list(Path(tmp_path).rglob("*.jpg"))
    settings.r2_public_url = ""
    with pytest.raises(ValueError, match="incomplete"):
        media.store_image(SimpleNamespace(body=b"\xff\xd8\xfftest", name="photo.jpg"), "flowers")


def test_private_inquiry_upload_is_not_public_and_requires_private_bucket(monkeypatch, tmp_path):
    settings = SimpleNamespace(private_media_root=tmp_path / "private", media_root=tmp_path / "public",
        r2_endpoint_url="", r2_bucket="", r2_private_bucket="", r2_access_key_id="",
        r2_secret_access_key="", r2_public_url="", media_url="/media")
    monkeypatch.setattr(media, "get_settings", lambda: settings)
    key = media.store_private_image(SimpleNamespace(body=b"\xff\xd8\xfftest", name="photo.jpg"))
    assert media.read_private_image(key) == (b"\xff\xd8\xfftest", "image/jpeg")
    assert not settings.media_root.exists()
    with pytest.raises(ValueError):
        media.read_private_image("../secrets.jpg")
    settings.r2_endpoint_url = "https://account.r2.cloudflarestorage.com"
    settings.r2_bucket = "public"
    with pytest.raises(ValueError, match="Private R2"):
        media.store_private_image(SimpleNamespace(body=b"\xff\xd8\xfftest", name="photo.jpg"))
