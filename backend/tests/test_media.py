from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import boto3
import pytest
from PIL import Image, ImageCms
from sqlalchemy import select

from app import media
from app.admin import CSRF_COOKIE
from app.auth import hash_password
from app.db import session_scope
from app.models import FlowerListing, GalleryImage, SiteContent, User
from app.server import app
from app.settings import get_settings


@pytest.mark.asyncio
async def test_gallery_focal_and_listing_photo_reuse(tmp_path, monkeypatch, real_image):

    monkeypatch.setattr(get_settings(), "media_root", tmp_path)
    async with session_scope() as db:
        db.add(User(email="owner@example.com", password_hash=hash_password("password"), is_admin=True))
        db.add(FlowerListing(name="Zinnia", price=Decimal("3.00"), quantity_available=2))
        await db.commit()
    await app.asgi_client.get("/admin/login")
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    await app.asgi_client.post(
        "/admin/login", data=dict(email="owner@example.com", password="password", csrf_token=token)
    )
    await app.asgi_client.get("/admin/gallery/new")
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    _, created = await app.asgi_client.post(
        "/admin/gallery/new",
        data=dict(
            csrf_token=token,
            alt_text="Sunlit yellow zinnia",
            caption="Morning harvest",
            sort_order="1",
            focal_x="25",
            focal_y="70",
            active="on",
        ),
        files={"image": ("sun.png", real_image(format="PNG"), "image/png")},
    )
    assert created.status == 302
    _, gallery = await app.asgi_client.get("/api/gallery/")
    assert gallery.json[0]["focal_x"] == 25 and gallery.json[0]["focal_y"] == 70
    assert gallery.json[0]["image"].endswith(".webp")
    await app.asgi_client.get("/admin/flowers/1")
    token = app.asgi_client.cookies.get(CSRF_COOKIE)
    _, reused = await app.asgi_client.post(
        "/admin/flowers/1", data=dict(csrf_token=token, name="Zinnia", price="3.00", gallery_image_id="1")
    )
    assert reused.status == 302
    async with session_scope() as db:
        listing = await db.get(FlowerListing, 1)
        photo = await db.scalar(select(GalleryImage.image))
        assert listing.photo == photo
        listing.channel = "both"
        listing.active = True
        db.add(SiteContent(id=1, content={"photos": {"home_hero": 1}}))
        await db.commit()
    _, retail = await app.asgi_client.get("/api/retail/flowers/")
    assert retail.json[0]["photo_url"] == gallery.json[0]["image"]
    _, content = await app.asgi_client.get("/api/site-content/")
    assert content.json["content"]["photos"]["home_hero"]["image"] == gallery.json[0]["image"]


@pytest.mark.asyncio
async def test_existing_gallery_key_is_not_rewritten():
    async with session_scope() as db:
        db.add(GalleryImage(image="gallery/2026/10/original.jpg", alt_text="Existing photo"))
        await db.commit()
    _, response = await app.asgi_client.get("/api/gallery/")
    assert response.json[0]["image"].endswith("/gallery/2026/10/original.jpg")


def test_image_upload_validates_and_stores_display_only(tmp_path, monkeypatch, real_image):
    settings = SimpleNamespace(
        media_root=tmp_path,
        media_url="/media",
        r2_endpoint_url="",
        r2_bucket="",
        r2_access_key_id="",
        r2_secret_access_key="",
        r2_public_url="",
    )
    monkeypatch.setattr(media, "get_settings", lambda: settings)
    with pytest.raises(ValueError, match="PNG"):
        media.store_image(SimpleNamespace(body=b"<svg><script>alert(1)</script></svg>", name="evil.svg"), "gallery")
    with pytest.raises(ValueError, match="50 MiB"):
        media.store_image(SimpleNamespace(body=b"\x89PNG\r\n\x1a\n" + b"0" * media.MAX_IMAGE_BYTES), "gallery")
    path = media.store_image(SimpleNamespace(body=real_image(format="PNG"), name="../unsafe.php"), "gallery")
    assert path.startswith("gallery/") and path.endswith(".webp")
    with Image.open(tmp_path / path) as image:
        assert image.format == "WEBP" and image.size == (80, 60)
    assert len([p for p in tmp_path.rglob("*") if p.is_file()]) == 1
    assert media.public_media_url() == "/media"


def test_r2_upload_requires_complete_config_and_writes_object(monkeypatch, tmp_path, real_image):

    settings = SimpleNamespace(
        media_root=tmp_path,
        media_url="/media",
        r2_endpoint_url="https://account.r2.cloudflarestorage.com",
        r2_bucket="photos",
        r2_access_key_id="test",
        r2_secret_access_key="secret",
        r2_public_url="https://images.example.com",
    )
    monkeypatch.setattr(media, "get_settings", lambda: settings)
    uploaded = []
    monkeypatch.setattr(
        boto3, "client", lambda *args, **kwargs: SimpleNamespace(put_object=lambda **kwargs: uploaded.append(kwargs))
    )
    key = media.store_image(SimpleNamespace(body=real_image(), name="photo.jpg"), "flowers")
    assert len(uploaded) == 1
    assert uploaded[0]["Bucket"] == "photos" and uploaded[0]["ContentType"] == "image/webp"
    assert uploaded[0]["CacheControl"] == "public, max-age=31536000, immutable"
    assert uploaded[0]["Key"] == key and media.public_media_url() == "https://images.example.com"
    assert not list(Path(tmp_path).rglob("*.jpg"))
    settings.r2_public_url = ""
    with pytest.raises(ValueError, match="incomplete"):
        media.store_image(SimpleNamespace(body=real_image(), name="photo.jpg"), "flowers")


def test_full_resolution_photo_is_optimized(monkeypatch, tmp_path):
    settings = SimpleNamespace(
        media_root=tmp_path,
        media_url="/media",
        r2_endpoint_url="https://account.r2.cloudflarestorage.com",
        r2_bucket="photos",
        r2_access_key_id="test",
        r2_secret_access_key="secret",
        r2_public_url="https://images.example.com",
    )
    monkeypatch.setattr(media, "get_settings", lambda: settings)
    uploaded = []
    monkeypatch.setattr(
        boto3, "client", lambda *args, **kwargs: SimpleNamespace(put_object=lambda **kwargs: uploaded.append(kwargs))
    )
    with Image.effect_noise((4000, 6000), 64).convert("RGB") as image:
        output = BytesIO()
        image.save(output, format="JPEG", quality=98)
        body = output.getvalue()
    assert 10 * 1024 * 1024 < len(body) < media.MAX_IMAGE_BYTES

    key = media.store_image(SimpleNamespace(body=body, name="professional-photo.jpg"), "gallery")

    assert uploaded[0]["Bucket"] == "photos"
    display = uploaded[0]["Body"]
    assert len(display) <= media.MAX_DISPLAY_BYTES and len(display) < len(body) / 5
    with Image.open(BytesIO(display)) as image:
        assert image.format == "WEBP" and image.size == (1600, 2400)
    assert len(uploaded) == 1
    assert uploaded[0]["ContentType"] == "image/webp"
    assert uploaded[0]["Key"] == key


def test_private_inquiry_upload_is_not_public_and_requires_private_bucket(monkeypatch, tmp_path, real_image):
    settings = SimpleNamespace(
        private_media_root=tmp_path / "private",
        media_root=tmp_path / "public",
        r2_endpoint_url="",
        r2_bucket="",
        r2_private_bucket="",
        r2_access_key_id="",
        r2_secret_access_key="",
        r2_public_url="",
        media_url="/media",
    )
    monkeypatch.setattr(media, "get_settings", lambda: settings)
    body = real_image()
    key = media.store_private_image(SimpleNamespace(body=body, name="photo.jpg"))
    assert media.read_private_image(key) == (body, "image/jpeg")
    assert not settings.media_root.exists()
    with pytest.raises(ValueError):
        media.read_private_image("../secrets.jpg")
    settings.r2_endpoint_url = "https://account.r2.cloudflarestorage.com"
    settings.r2_bucket = "public"
    with pytest.raises(ValueError, match="Private R2"):
        media.store_private_image(SimpleNamespace(body=body, name="photo.jpg"))
    settings.r2_access_key_id = "test"
    settings.r2_secret_access_key = "test"
    settings.r2_private_bucket = "public"
    with pytest.raises(ValueError, match="separate"):
        media.store_private_image(SimpleNamespace(body=body))
    settings.r2_private_bucket = "private"
    uploaded = []
    monkeypatch.setattr(boto3, "client", lambda *a, **kw: SimpleNamespace(put_object=lambda **kw: uploaded.append(kw)))
    media.store_private_image(SimpleNamespace(body=body))
    assert len(uploaded) == 1
    assert uploaded[0]["Bucket"] == "private" and uploaded[0]["Body"] == body
    assert uploaded[0]["ContentType"] == "image/jpeg"
    assert uploaded[0]["CacheControl"] == "private, no-store"


@pytest.mark.parametrize("body", [b"\xff\xd8\xfftest", b"\x89PNG\r\n\x1a\nexample", b"RIFF0000WEBP", b"GIF89a", b""])
@pytest.mark.parametrize("public", [False, True])
def test_invalid_images_are_rejected(body, public):
    with pytest.raises(ValueError):
        media._image_details(SimpleNamespace(body=body), public=public)


@pytest.mark.parametrize("public", [False, True])
def test_truncated_real_image_is_rejected(real_image, public):
    body = real_image(size=(800, 600))
    with pytest.raises(ValueError, match="valid, complete"):
        media._image_details(SimpleNamespace(body=body[:-100]), public=public)


def test_pixel_limit_before_decode(monkeypatch, real_image):
    body = real_image(format="PNG", size=(100, 100))
    monkeypatch.setattr(media, "MAX_DECODED_PIXELS", 9999)
    monkeypatch.setattr(Image.Image, "load", lambda self: pytest.fail("oversize image decoded"))
    with pytest.raises(ValueError, match="decoded pixels"):
        media._image_details(SimpleNamespace(body=body), public=True)


def test_edge_limit_before_decode(monkeypatch, real_image):
    body = real_image(format="PNG", size=(101, 1))
    monkeypatch.setattr(media, "MAX_IMAGE_EDGE", 100)
    monkeypatch.setattr(Image.Image, "load", lambda self: pytest.fail("oversize image decoded"))
    with pytest.raises(ValueError, match="edge"):
        media._image_details(SimpleNamespace(body=body))


def test_display_byte_cap_reduces_dimensions(monkeypatch):
    with Image.effect_noise((800, 600), 64).convert("RGB") as image:
        output = BytesIO()
        image.save(output, format="PNG")
    monkeypatch.setattr(media, "MAX_DISPLAY_BYTES", 20_000)
    display, _, _ = media._image_details(SimpleNamespace(body=output.getvalue()), public=True)
    assert len(display) <= 20_000
    with Image.open(BytesIO(display)) as image:
        assert image.width < 800 and image.height < 600


def test_invalid_icc_is_rejected_without_rejecting_private_original(real_image):
    body = real_image(icc_profile=b"invalid profile")
    with pytest.raises(ValueError, match="sRGB"):
        media._image_details(SimpleNamespace(body=body), public=True)
    assert media._image_details(SimpleNamespace(body=body))[0] == body


def test_pillow_decompression_bomb_is_rejected(monkeypatch, real_image):
    body = real_image(format="PNG", size=(100, 100))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 4000)
    with pytest.raises(ValueError, match="decoded pixels"):
        media._image_details(SimpleNamespace(body=body))


def test_orientation_color_and_metadata(real_image):
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "private camera owner"
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    body = real_image(size=(120, 80), exif=exif, icc_profile=profile)
    display, suffix, content_type = media._image_details(SimpleNamespace(body=body), public=True)
    with Image.open(BytesIO(display)) as image:
        assert image.size == (80, 120) and image.mode == "RGB"
        assert not image.getexif() and not image.info.get("icc_profile")
        assert image.getpixel((40, 40))[1] > 100
    assert suffix == ".webp" and content_type == "image/webp"


@pytest.mark.parametrize("mode", ["RGBA", "LA", "P", "CMYK"])
def test_alpha_palette_and_cmyk(mode):
    image = Image.new(mode, (40, 30))
    if mode == "P":
        image.info["transparency"] = 0
    output = BytesIO()
    image.save(output, format="JPEG" if mode == "CMYK" else "PNG")
    display, _, _ = media._image_details(SimpleNamespace(body=output.getvalue()), public=True)
    with Image.open(BytesIO(display)) as converted:
        assert converted.size == (40, 30)
        if mode != "CMYK":
            assert converted.mode == "RGBA" and converted.getpixel((0, 0))[3] == 0
        else:
            assert converted.mode == "RGB"
    image.close()


def test_animation_is_validated_and_only_first_frame_is_public(monkeypatch):
    output = BytesIO()
    with Image.new("RGB", (50, 50), "red") as first, Image.new("RGB", (50, 50), "blue") as second:
        first.save(output, format="GIF", save_all=True, append_images=[second])
    body = output.getvalue()
    assert media._image_details(SimpleNamespace(body=body))[0] == body
    display, _, _ = media._image_details(SimpleNamespace(body=body), public=True)
    with Image.open(BytesIO(display)) as image:
        assert image.n_frames == 1
        assert image.getpixel((20, 20))[0] > 200
    monkeypatch.setattr(media, "MAX_DECODED_PIXELS", 4999)
    with pytest.raises(ValueError, match="across"):
        media._image_details(SimpleNamespace(body=body))
    monkeypatch.setattr(media, "MAX_DECODED_PIXELS", 5000)
    monkeypatch.setattr(media, "MAX_IMAGE_FRAMES", 1)
    with pytest.raises(ValueError, match="frames"):
        media._image_details(SimpleNamespace(body=body))


def test_overlapping_public_and_private_decodes_do_not_queue(monkeypatch, real_image):
    entered, release = Event(), Event()
    original = media._display_image

    def held_display(image):
        entered.set()
        assert release.wait(timeout=5)
        return original(image)

    monkeypatch.setattr(media, "_display_image", held_display)
    upload = SimpleNamespace(body=real_image())
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(media._image_details, upload, public=True)
        try:
            assert entered.wait(timeout=5)
            with pytest.raises(ValueError, match="retry"):
                media._image_details(upload)  # Private shares the decode budget.
        finally:
            release.set()
        assert first.result(timeout=5)[1] == ".webp"


def test_concurrent_decode_fails_fast_and_slot_is_released(real_image):
    upload = SimpleNamespace(body=real_image())
    assert media._image_slot.acquire(blocking=False)
    try:
        with pytest.raises(ValueError, match="retry"):
            media._image_details(upload, public=True)
    finally:
        media._image_slot.release()
    with pytest.raises(ValueError):
        media._image_details(SimpleNamespace(body=b"bad image"))
    assert media._image_details(upload, public=True)[1] == ".webp"
