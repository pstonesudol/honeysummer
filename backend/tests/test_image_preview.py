"""Admin image previews preserve saved photos until a replacement is submitted."""

import pytest

from app.admin import CSRF_COOKIE
from app.auth import hash_password
from app.db import session_scope
from app.models import GalleryImage, User
from app.server import app


@pytest.mark.asyncio
async def test_gallery_upload_has_large_preview_and_saved_image_fallback():
    async with session_scope() as db:
        db.add(User(email="preview@example.com", password_hash=hash_password("password"), is_admin=True))
        photo = GalleryImage(image="gallery/saved.webp", alt_text="Garden flowers")
        db.add(photo)
        await db.commit()
        photo_id = photo.id

    await app.asgi_client.get("/admin/login")
    csrf = app.asgi_client.cookies.get(CSRF_COOKIE)
    await app.asgi_client.post(
        "/admin/login", data=dict(email="preview@example.com", password="password", csrf_token=csrf)
    )
    _, empty = await app.asgi_client.get("/admin/gallery/new")
    assert empty.status == 200
    assert '<figure class="image-upload__preview" hidden>' in empty.text
    assert 'aria-describedby="f-image-status"' in empty.text
    assert "data-clear-image hidden" in empty.text
    assert "object-fit:contain" in empty.text

    _, existing = await app.asgi_client.get(f"/admin/gallery/{photo_id}")
    assert existing.status == 200
    assert '<figure class="image-upload__preview" >' in existing.text
    assert 'data-current-src="' in existing.text and "/gallery/saved.webp" in existing.text
    assert "Current photo. Choose a new image to replace it." in existing.text
    assert "Selected, not yet saved" in existing.text
