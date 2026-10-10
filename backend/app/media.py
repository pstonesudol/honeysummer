"""Validated immutable image storage; R2 when configured, local only in development."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from .settings import get_settings


def public_media_url() -> str:
    settings = get_settings()
    return (settings.r2_public_url or settings.media_url).rstrip("/")


def _image_details(upload) -> tuple[bytes, str, str]:
    body = upload.body
    if not body or len(body) > 8 * 1024 * 1024:
        raise ValueError("Choose an image smaller than 8 MB.")
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        suffix, content_type = ".png", "image/png"
    elif body.startswith(b"\xff\xd8\xff"):
        suffix, content_type = ".jpg", "image/jpeg"
    elif body.startswith((b"GIF87a", b"GIF89a")):
        suffix, content_type = ".gif", "image/gif"
    elif body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        suffix, content_type = ".webp", "image/webp"
    else:
        raise ValueError("Upload a PNG, JPEG, WebP or GIF image (not an SVG).")
    return body, suffix, content_type


def store_image(upload, subdir: str) -> str:
    body, suffix, content_type = _image_details(upload)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    key = f"{subdir}/{now:%Y}/{now:%m}/{uuid4().hex}{suffix}"
    settings = get_settings()
    configured = [settings.r2_endpoint_url, settings.r2_bucket, settings.r2_access_key_id,
                  settings.r2_secret_access_key, settings.r2_public_url]
    if any(configured):
        if not all(configured) or not settings.r2_public_url.startswith("https://"):
            raise ValueError("R2 storage is incomplete; image was not saved.")
        import boto3
        client = boto3.client("s3", endpoint_url=settings.r2_endpoint_url,
                              aws_access_key_id=settings.r2_access_key_id,
                              aws_secret_access_key=settings.r2_secret_access_key,
                              region_name="auto")
        client.put_object(Bucket=settings.r2_bucket, Key=key, Body=body,
                          ContentType=content_type, CacheControl="public, max-age=31536000, immutable")
    else:
        destination = Path(settings.media_root) / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
    return key


def store_private_image(upload) -> str:
    """Never put customer inspiration photos in the public /media tree or R2 CDN."""
    body, suffix, content_type = _image_details(upload)
    key = f"inquiries/{uuid4().hex}{suffix}"
    settings = get_settings()
    if any((settings.r2_endpoint_url, settings.r2_bucket, settings.r2_private_bucket,
            settings.r2_access_key_id, settings.r2_secret_access_key, settings.r2_public_url)):
        if not all((settings.r2_endpoint_url, settings.r2_access_key_id,
                    settings.r2_secret_access_key, settings.r2_private_bucket)):
            raise ValueError("Private R2 storage is incomplete; photo was not saved.")
        if settings.r2_private_bucket == settings.r2_bucket:
            raise ValueError("Customer photos require a private bucket separate from public images.")
        import boto3
        boto3.client("s3", endpoint_url=settings.r2_endpoint_url,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto").put_object(Bucket=settings.r2_private_bucket, Key=key,
                Body=body, ContentType=content_type, CacheControl="private, no-store")
    else:
        destination = settings.private_media_root / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
    return key


def read_private_image(key: str) -> tuple[bytes, str]:
    if not key.startswith("inquiries/") or "/" in key.removeprefix("inquiries/"):
        raise ValueError("Invalid private photo path.")
    content_type = {".png": "image/png", ".jpg": "image/jpeg", ".gif": "image/gif",
                    ".webp": "image/webp"}.get(Path(key).suffix)
    if not content_type:
        raise ValueError("Invalid private photo type.")
    settings = get_settings()
    if settings.r2_private_bucket:
        import boto3
        content = boto3.client("s3", endpoint_url=settings.r2_endpoint_url,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto").get_object(Bucket=settings.r2_private_bucket, Key=key)["Body"].read()
    else:
        content = (settings.private_media_root / key).read_bytes()
    return content, content_type
