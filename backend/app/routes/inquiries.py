"""Inquiry intake: bouquet, wedding, and general contact requests."""

import json
import asyncio

from sanic import Blueprint
from sanic.response import json as json_response

from ..db import session_scope
from ..emails import send_inquiry_emails
from ..models import Inquiry, InquiryCorrespondence
from ..schemas import InquiryOut
from ..media import store_private_image

bp = Blueprint("inquiries", url_prefix="/api")

KINDS = {"bouquet", "wedding", "contact"}
MAX_PHOTO_BYTES = 8 * 1024 * 1024


def _string(form, key: str) -> str:
    value = form.get(key)
    return value.strip() if isinstance(value, str) else ""


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
            errors["photo"] = ["Photos must be 8 MB or smaller."]

    if errors:
        return json_response(errors, status=400)

    try:
        photo_path = await asyncio.to_thread(store_private_image, upload) if upload and upload.name else ""
    except ValueError as exc:
        return json_response({"photo": [str(exc)]}, status=400)
    except Exception:
        return json_response({"photo": ["Photo storage is unavailable. Please try again later."]}, status=503)

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

    outcomes = await asyncio.to_thread(send_inquiry_emails, inquiry)
    async with session_scope() as session:
        current = await session.get(Inquiry, inquiry.id)
        current.email_delivery = outcomes
        if outcomes["customer"] == "accepted":
            session.add(InquiryCorrespondence(inquiry_id=inquiry.id, actor_id=None,
                direction="sent", subject="We received your note — Honey Summer",
                summary="Automatic inquiry acknowledgement accepted by email provider; delivery is not confirmed."))
        await session.commit()

    payload = InquiryOut.model_validate(inquiry).model_dump(mode="json")
    if inquiry.photo:
        payload["photo"] = "Received privately; visible only to the shop owner."
    return json_response(payload, status=201)
