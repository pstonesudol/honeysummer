"""Transactional email via Resend, with a console fallback in development."""

from __future__ import annotations

import logging

from .models import Inquiry
from .settings import get_settings

logger = logging.getLogger(__name__)

KIND_LABELS = {
    "bouquet": "Bouquet request",
    "wedding": "Wedding & event inquiry",
    "contact": "General contact",
    "wholesale": "Wholesale access request",
}


def send_email(*, subject: str, body: str, to: str, reply_to: str | None = None) -> None:
    """Send one email through Resend, or log it when no key is configured."""
    settings = get_settings()
    if settings.resend_api_key:
        import resend

        resend.api_key = settings.resend_api_key
        params: dict = {
            "from": settings.default_from_email,
            "to": [to],
            "subject": subject,
            "text": body,
        }
        if reply_to:
            params["reply_to"] = reply_to
        resend.Emails.send(params)
        return
    logger.info("Email to %s · %s\n%s", to, subject, body)


def _format_details(details: dict) -> list[str]:
    lines = []
    for key, value in (details or {}).items():
        label = key.replace("_", " ").capitalize()
        if isinstance(value, bool):
            value = "Yes" if value else "No"
        elif isinstance(value, list):
            value = ", ".join(str(item) for item in value)
        lines.append(f"{label}: {value}")
    return lines


def _notification_body(inquiry: Inquiry) -> str:
    lines = [
        f"New {KIND_LABELS.get(inquiry.kind, inquiry.kind)} from the Honey Summer website.",
        "",
        f"Name: {inquiry.name}",
        f"Email: {inquiry.email}",
    ]
    if inquiry.phone:
        lines.append(f"Phone: {inquiry.phone}")
    if inquiry.message:
        lines.extend(["", inquiry.message])
    detail_lines = _format_details(inquiry.details)
    if detail_lines:
        lines.extend(["", *detail_lines])
    if inquiry.photo:
        lines.extend(["", f"Inspiration photo attached: {inquiry.photo}"])
    return "\n".join(lines)


def _acknowledgement_body(inquiry: Inquiry) -> str:
    return "\n".join(
        [
            f"Thank you for reaching out to Honey Summer, {inquiry.name}!",
            "",
            "This note confirms that your message arrived safely. "
            "Isabella reads every inquiry personally and will reply within a "
            "few days.",
            "",
            "In the meantime, a reminder that Honey Summer grows with the "
            "seasons, so what is available shifts week to week.",
            "",
            "With warmth,",
            "Honey Summer",
        ]
    )


def send_inquiry_emails(inquiry: Inquiry) -> None:
    """Notify the farm and acknowledge the sender.

    Email failures are logged rather than raised so a transient mail problem
    never loses a submitted inquiry.
    """
    settings = get_settings()
    subject = f"Honey Summer — {KIND_LABELS.get(inquiry.kind, inquiry.kind)}"
    try:
        send_email(
            subject=subject,
            body=_notification_body(inquiry),
            to=settings.inquiry_notification_email,
            reply_to=inquiry.email,
        )
        send_email(
            subject="We received your note — Honey Summer",
            body=_acknowledgement_body(inquiry),
            to=inquiry.email,
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("Unable to send inquiry emails for inquiry %s", inquiry.id)
