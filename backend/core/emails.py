import logging

from django.conf import settings
from django.core.mail import EmailMessage, send_mail

logger = logging.getLogger(__name__)

KIND_LABELS = {
    "bouquet": "Bouquet request",
    "wedding": "Wedding & event inquiry",
    "contact": "General contact",
    "wholesale": "Wholesale access request",
}


def _format_details(details):
    lines = []
    for key, value in (details or {}).items():
        label = key.replace("_", " ").capitalize()
        if isinstance(value, bool):
            value = "Yes" if value else "No"
        elif isinstance(value, list):
            value = ", ".join(str(item) for item in value)
        lines.append(f"{label}: {value}")
    return lines


def _notification_body(inquiry):
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
        lines.extend(["", f"Inspiration photo attached: {inquiry.photo.name}"])
    return "\n".join(lines)


def _acknowledgement_body(inquiry):
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


def send_inquiry_emails(inquiry):
    """Notify the farm and acknowledge the sender.

    Email failures are logged rather than raised so a transient mail problem
    never loses a submitted inquiry.
    """
    subject = f"Honey Summer — {KIND_LABELS.get(inquiry.kind, inquiry.kind)}"
    try:
        notification = EmailMessage(
            subject,
            _notification_body(inquiry),
            settings.DEFAULT_FROM_EMAIL,
            [settings.INQUIRY_NOTIFICATION_EMAIL],
            reply_to=[inquiry.email],
        )
        notification.send()
        send_mail(
            "We received your note — Honey Summer",
            _acknowledgement_body(inquiry),
            settings.DEFAULT_FROM_EMAIL,
            [inquiry.email],
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("Unable to send inquiry emails for inquiry %s", inquiry.pk)


def send_order_emails(order):
    lines = [
        f"Thank you for your Honey Summer wholesale order #{order.pk}.", "",
        *[f"{item.quantity} × {item.name_snapshot} (${item.price_snapshot} each)" for item in order.items.all()],
        "", f"Fulfillment: {order.get_fulfillment_display()}",
    ]
    if order.pickup_window:
        lines.append(f"Pickup window: {order.pickup_window}")
    if order.delivery_address:
        lines.append(f"Delivery address: {order.delivery_address}")
    body = "\n".join(lines) + "\n\nIsabella will be in touch with final pickup or delivery details.\n\nWith warmth,\nHoney Summer"
    try:
        send_mail(f"Honey Summer wholesale order #{order.pk}", body, settings.DEFAULT_FROM_EMAIL, [order.customer.email], reply_to=[settings.INQUIRY_NOTIFICATION_EMAIL])
        send_mail(f"New Honey Summer wholesale order #{order.pk}", body, settings.DEFAULT_FROM_EMAIL, [settings.INQUIRY_NOTIFICATION_EMAIL], reply_to=[order.customer.email])
    except Exception:  # pragma: no cover
        logger.exception("Unable to send order emails for order %s", order.pk)


def send_signup_notification(profile):
    try:
        send_mail(
            "New Honey Summer wholesale account request",
            f"{profile.business_name} ({profile.user.email}) requested wholesale access. Review and approve them in Django admin.",
            settings.DEFAULT_FROM_EMAIL,
            [settings.INQUIRY_NOTIFICATION_EMAIL],
        )
    except Exception:  # pragma: no cover
        logger.exception("Unable to send wholesale signup notification")
