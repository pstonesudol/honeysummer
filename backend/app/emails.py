"""Transactional email via Resend, with a console fallback in development."""

from __future__ import annotations

import logging
from decimal import Decimal

import resend

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
ORDER_LABELS = {"wholesale": "wholesale order", "retail": "order"}


def send_email(
    *,
    subject: str,
    body: str,
    to: str,
    reply_to: str | None = None,
    html_body: str | None = None,
    idempotency_key: str | None = None,
) -> None:
    """Send one email through Resend, or log it when no key is configured."""
    settings = get_settings()
    if settings.resend_api_key:
        resend.api_key = settings.resend_api_key
        params: dict = {
            "from": settings.default_from_email,
            "to": [to],
            "subject": subject,
            "text": body,
        }
        if reply_to:
            params["reply_to"] = reply_to
        if html_body:
            params["html"] = html_body
        if idempotency_key:
            resend.Emails.send(params, {"idempotency_key": idempotency_key})
        else:
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


def send_inquiry_emails(inquiry: Inquiry) -> dict:
    """Notify the farm and acknowledge the sender.

    Email failures are logged rather than raised so a transient mail problem
    never loses a submitted inquiry.
    """
    settings = get_settings()
    subject = f"Honey Summer — {KIND_LABELS.get(inquiry.kind, inquiry.kind)}"
    outcomes = {}
    for recipient, params in (
        (
            "farm",
            dict(
                subject=subject,
                body=_notification_body(inquiry),
                to=settings.inquiry_notification_email,
                reply_to=inquiry.email,
            ),
        ),
        (
            "customer",
            dict(subject="We received your note — Honey Summer", body=_acknowledgement_body(inquiry), to=inquiry.email),
        ),
    ):
        try:
            send_email(**params)
            outcomes[recipient] = "accepted" if settings.resend_api_key else "logged locally"
        except Exception:  # pragma: no cover - defensive
            logger.exception("Unable to send %s inquiry email for inquiry %s", recipient, inquiry.id)
            outcomes[recipient] = "failed"
    return outcomes


def send_signup_notification(*, business_name: str, email: str, contact_name: str = "") -> None:
    """Tell the farm that a florist requested wholesale access."""
    try:
        send_email(
            subject="New Honey Summer wholesale account request",
            body=(
                f"{contact_name} at {business_name} ({email}) requested wholesale access. "
                "Review and approve them in the admin."
            ),
            to=get_settings().inquiry_notification_email,
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("Unable to send wholesale signup notification")


def send_wholesale_approval_email(*, email: str) -> None:
    """Tell an approved florist they can sign in with their existing account."""
    try:
        send_email(
            subject="Your Honey Summer wholesale account is approved",
            body=(
                "Your wholesale account is approved. Sign in with the email and password "
                "you chose when requesting access: "
                f"{get_settings().checkout_success_url.split('?')[0]}"
            ),
            to=email,
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("Unable to send wholesale approval email to %s", email)


def send_order_emails(
    *,
    order_id: int,
    order_reference: str | None = None,
    fulfillment: str,
    pickup_window: str,
    delivery_address: str,
    customer_email: str,
    items: list[dict],
    channel: str = "wholesale",
    customer_name: str = "",
    delivery_fee: Decimal | int | float = 0,
    recipient: str | None = None,
    raise_errors: bool = False,
) -> None:
    """Confirm an order to the buyer and notify the farm.

    Wholesale confirmations go to the approved florist; retail confirmations
    go to the guest who checked out.
    """
    settings = get_settings()
    label = ORDER_LABELS.get(channel, "order")
    reference = order_reference or f"HS{order_id:06d}"
    lines = [f"Thank you for your Honey Summer {label} {reference}.", ""]
    lines.extend(f"{item['quantity']} × {item['name']} (${item['price']} each)" for item in items)
    lines.extend(["", f"Fulfillment: {FULFILLMENT_LABELS.get(fulfillment, fulfillment)}"])
    if pickup_window:
        lines.append(f"Pickup window: {pickup_window}")
    if delivery_address:
        lines.append(f"Delivery address: {delivery_address}")
    try:
        if delivery_fee and float(delivery_fee) > 0:
            lines.append(f"Delivery fee: ${float(delivery_fee):.2f}")
    except TypeError, ValueError:  # pragma: no cover - defensive
        pass
    body = (
        "\n".join(lines) + "\n\nIsabella will be in touch with final pickup or delivery details."
        "\n\nWith warmth,\nHoney Summer"
    )
    try:
        if recipient in (None, "customer"):
            send_email(
                subject=f"Honey Summer {label} {reference}",
                body=body,
                to=customer_email,
                reply_to=settings.inquiry_notification_email,
            )
        if recipient in (None, "farm"):
            send_email(
                subject=f"New Honey Summer {label} {reference}",
                body=body,
                to=settings.inquiry_notification_email,
                reply_to=customer_email,
            )
    except Exception:  # pragma: no cover - defensive
        logger.exception("Unable to send order emails for order %s", order_id)
        if raise_errors:
            raise
