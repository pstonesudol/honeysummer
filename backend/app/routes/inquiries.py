"""Inquiry intake: bouquet, wedding, and general contact requests."""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sanic import Blueprint
from sanic.response import json as json_response

from ..db import session_scope
from ..emails import send_inquiry_emails
from ..models import Inquiry
from ..schemas import InquiryOut
from ..settings import get_settings

bp = Blueprint("inquiries", url_prefix="/api")

KINDS = {"bouquet", "wedding", "contact"}
MAX_PHOTO_BYTES = 10 * 1024 * 1024


def _string(form, key: str) -> str:
    value = form.get(key)
    return value.strip() if isinstance(value, str) else ""


def _save_photo(upload, media_root: Path) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(upload.name).name) or "photo"
    now = datetime.now(timezone.utc)
    rel_dir = Path("inquiries") / f"{now:%Y}" / f"{now:%m}"
    dest_dir = media_root / rel_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}_{safe_name}"
    (dest_dir / filename).write_bytes(upload.body)
    return str(rel_dir / filename)


@bp.post("/inquiries/")
async def create_inquiry(request):
    form = request.form
    kind = _string(form, "kind")
    name = _string(form, "name")
    email = _string(form, "email")

    errors: dict[str, list[str]] = {}
    if kind not in KINDS:
        errors["kind"] = ["Select a valid inquiry type."]
    if not name:
        errors["name"] = ["This field is required."]
    if not email or "@" not in email:
        errors["email"] = ["Enter a valid email address."]

    details: dict = {}
    raw_details = form.get("details")
    if raw_details:
        try:
            details = json.loads(raw_details)
            if not isinstance(details, dict):
                raise ValueError
        except (ValueError, TypeError):
            errors["details"] = ["Details must be an object."]

    upload = request.files.get("photo")
    if upload and upload.name:
        if upload.type and not upload.type.startswith("image/"):
            errors["photo"] = ["Please upload an image file."]
        elif len(upload.body) > MAX_PHOTO_BYTES:
            errors["photo"] = ["Photos must be 10 MB or smaller."]

    if errors:
        return json_response(errors, status=400)

    photo_path = _save_photo(upload, get_settings().media_root) if upload and upload.name else ""

    async with session_scope() as session:
        inquiry = Inquiry(
            kind=kind,
            name=name,
            email=email,
            phone=_string(form, "phone"),
            message=_string(form, "message"),
            details=details,
            photo=photo_path,
        )
        session.add(inquiry)
        await session.commit()
        await session.refresh(inquiry)

    send_inquiry_emails(inquiry)

    payload = InquiryOut.model_validate(inquiry).model_dump(mode="json")
    if inquiry.photo:
        payload["photo"] = f"{get_settings().media_url.rstrip('/')}/{inquiry.photo}"
    return json_response(payload, status=201)
