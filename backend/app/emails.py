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

FULFILLMENT_LABELS = {"pickup": "Pickup", "delivery": "Delivery"}


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


def send_signup_notification(*, business_name: str, email: str) -> None:
    """Tell the farm that a florist requested wholesale access."""
    try:
        send_email(
            subject="New Honey Summer wholesale account request",
            body=(
                f"{business_name} ({email}) requested wholesale access. "
                "Review and approve them in the admin."
            ),
            to=get_settings().inquiry_notification_email,
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("Unable to send wholesale signup notification")


def send_order_emails(
    *,
    order_id: int,
    fulfillment: str,
    pickup_window: str,
    delivery_address: str,
    customer_email: str,
    items: list[dict],
) -> None:
    """Confirm a wholesale order to the florist and notify the farm."""
    settings = get_settings()
    lines = [f"Thank you for your Honey Summer wholesale order #{order_id}.", ""]
    lines.extend(
        f"{item['quantity']} × {item['name']} (${item['price']} each)" for item in items
    )
    lines.extend(["", f"Fulfillment: {FULFILLMENT_LABELS.get(fulfillment, fulfillment)}"])
    if pickup_window:
        lines.append(f"Pickup window: {pickup_window}")
    if delivery_address:
        lines.append(f"Delivery address: {delivery_address}")
    body = (
        "\n".join(lines)
        + "\n\nIsabella will be in touch with final pickup or delivery details."
        "\n\nWith warmth,\nHoney Summer"
    )
    try:
        send_email(
            subject=f"Honey Summer wholesale order #{order_id}",
            body=body,
            to=customer_email,
            reply_to=settings.inquiry_notification_email,
        )
        send_email(
            subject=f"New Honey Summer wholesale order #{order_id}",
            body=body,
            to=settings.inquiry_notification_email,
            reply_to=customer_email,
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("Unable to send order emails for order %s", order_id)
