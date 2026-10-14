"""Validated immutable image storage; R2 when configured, local only in development."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from threading import BoundedSemaphore
from uuid import uuid4

import boto3
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

from .settings import get_settings

MAX_IMAGE_BYTES = 50 * 1024 * 1024
MAX_DECODED_PIXELS = 40_000_000
MAX_IMAGE_EDGE = 16_000
MAX_IMAGE_FRAMES = 100
MAX_DISPLAY_EDGE = 2400
MAX_DISPLAY_BYTES = 2 * 1024 * 1024
# Fail fast: do not queue full-resolution decodes in this process.
_image_slot = BoundedSemaphore(1)
_IMAGE_TYPES = {
    "PNG": (".png", "image/png"),
    "JPEG": (".jpg", "image/jpeg"),
    "GIF": (".gif", "image/gif"),
    "WEBP": (".webp", "image/webp"),
}


def public_media_url() -> str:
    """Return the public base URL for stored media."""
    settings = get_settings()
    return (settings.r2_public_url or settings.media_url).rstrip("/")


def _image_details(upload, *, public: bool = False) -> tuple[bytes, str, str]:
    body = upload.body
    if not body or len(body) > MAX_IMAGE_BYTES:
        raise ValueError("Choose an image no larger than 50 MiB.")
    if not _image_slot.acquire(blocking=False):
        raise ValueError("Another image is being processed. Please retry shortly.")
    try:
        # Verify structure, then reopen and actually decode every frame,
        # including private originals. Header inspection alone is insufficient.
        with Image.open(BytesIO(body), formats=list(_IMAGE_TYPES)) as image:
            suffix, content_type = _IMAGE_TYPES[image.format]
            _check_dimensions(image)
            image.verify()
        with Image.open(BytesIO(body), formats=list(_IMAGE_TYPES)) as image:
            total_pixels = 0
            frame = 0
            while True:
                _check_dimensions(image)
                total_pixels += image.width * image.height
                if total_pixels > MAX_DECODED_PIXELS or frame >= MAX_IMAGE_FRAMES:
                    raise ValueError(
                        "Choose an image with at most 40 million decoded pixels across at most 100 frames."
                    )
                image.load()
                frame += 1
                try:
                    image.seek(frame)
                except EOFError:
                    break
            if public:
                image.seek(0)
                return _display_image(image), ".webp", "image/webp"
        return body, suffix, content_type
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Choose an image with at most 40 million decoded pixels.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("Upload a valid, complete PNG, JPEG, WebP or GIF image (not an SVG).") from exc
    finally:
        _image_slot.release()


def _check_dimensions(image: Image.Image) -> None:
    if image.width * image.height > MAX_DECODED_PIXELS or max(image.size) > MAX_IMAGE_EDGE:
        raise ValueError("Choose an image with at most 40 million decoded pixels and no edge over 16000 pixels.")


def _display_image(image: Image.Image) -> bytes:
    # Apply orientation before dropping EXIF, including location/camera metadata.
    # In-place transpose avoids retaining another full-resolution pixel buffer.
    ImageOps.exif_transpose(image, in_place=True)
    image.thumbnail((MAX_DISPLAY_EDGE, MAX_DISPLAY_EDGE), Image.Resampling.LANCZOS, reducing_gap=3)
    has_alpha = image.mode in ("RGBA", "LA") or "transparency" in image.info
    mode = "RGBA" if has_alpha else "RGB"
    icc = image.info.get("icc_profile")
    if icc:
        try:
            source = ImageCms.ImageCmsProfile(BytesIO(icc))
            if image.mode in ("P", "LA"):
                image = image.convert(mode)
            image = ImageCms.profileToProfile(image, source, ImageCms.createProfile("sRGB"), outputMode=mode)
        except (ImageCms.PyCMSError, OSError, ValueError) as exc:
            raise ValueError("Image color profile cannot be converted to sRGB. Export it as sRGB and retry.") from exc
    else:
        # Untagged images are assumed sRGB; Pillow converts untagged CMYK to RGB.
        image = image.convert(mode)
    try:
        while True:
            output = BytesIO()
            image.save(output, format="WEBP", quality=82, method=4, exif=b"", icc_profile=b"", xmp=b"")
            encoded = output.getvalue()
            if len(encoded) <= MAX_DISPLAY_BYTES:
                return encoded
            # Bound high-entropy images without lowering quality indefinitely.
            image.thumbnail((max(1, int(image.width * 0.8)), max(1, int(image.height * 0.8))), Image.Resampling.LANCZOS)
    finally:
        image.close()


def store_image(upload, subdir: str) -> str:
    """Store only an optimized public display image; never archive the original."""
    body, suffix, content_type = _image_details(upload, public=True)

    now = datetime.now(UTC)
    key = f"{subdir}/{now:%Y}/{now:%m}/{uuid4().hex}{suffix}"
    settings = get_settings()
    configured = [
        settings.r2_endpoint_url,
        settings.r2_bucket,
        settings.r2_access_key_id,
        settings.r2_secret_access_key,
        settings.r2_public_url,
    ]
    if any(configured):
        if not all(configured) or not settings.r2_public_url.startswith("https://"):
            raise ValueError("R2 storage is incomplete; image was not saved.")

        client = boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint_url,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
        )
        client.put_object(
            Bucket=settings.r2_bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",
        )
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
    if any(
        (
            settings.r2_endpoint_url,
            settings.r2_bucket,
            settings.r2_private_bucket,
            settings.r2_access_key_id,
            settings.r2_secret_access_key,
            settings.r2_public_url,
        )
    ):
        if not all(
            (
                settings.r2_endpoint_url,
                settings.r2_access_key_id,
                settings.r2_secret_access_key,
                settings.r2_private_bucket,
            )
        ):
            raise ValueError("Private R2 storage is incomplete; photo was not saved.")
        if settings.r2_private_bucket == settings.r2_bucket:
            raise ValueError("Customer photos require a private bucket separate from public images.")

        boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint_url,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
        ).put_object(
            Bucket=settings.r2_private_bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            CacheControl="private, no-store",
        )
    else:
        if settings.private_media_root.resolve().is_relative_to(settings.media_root.resolve()):
            raise ValueError("Private photo storage must be outside the public media directory.")
        destination = settings.private_media_root / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
    return key


def read_private_image(key: str) -> tuple[bytes, str]:
    """Read a private inquiry photo by its stored key."""
    if not key.startswith("inquiries/") or "/" in key.removeprefix("inquiries/"):
        raise ValueError("Invalid private photo path.")
    content_type = {".png": "image/png", ".jpg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}.get(
        Path(key).suffix
    )
    if not content_type:
        raise ValueError("Invalid private photo type.")
    settings = get_settings()
    if settings.r2_private_bucket:
        content = (
            boto3.client(
                "s3",
                endpoint_url=settings.r2_endpoint_url,
                aws_access_key_id=settings.r2_access_key_id,
                aws_secret_access_key=settings.r2_secret_access_key,
                region_name="auto",
            )
            .get_object(Bucket=settings.r2_private_bucket, Key=key)["Body"]
            .read()
        )
    else:
        content = (settings.private_media_root / key).read_bytes()
    return content, content_type
