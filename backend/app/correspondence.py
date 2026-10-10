"""Explicit .eml imports, never a mailbox connection or outbound sender."""

from datetime import UTC
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from hashlib import sha256


def parse_email(body: bytes, customer_email: str, direction: str) -> dict:
    """Validate an exported email and extract only plain-text correspondence."""
    if not body or len(body) > 1024 * 1024:
        raise ValueError("Choose an .eml email smaller than 1 MB.")
    if direction not in ("sent", "received"):
        raise ValueError("Choose sent or received.")
    message = BytesParser(policy=policy.default).parsebytes(body)
    header = "From" if direction == "received" else "To"
    addresses = {address.lower() for _, address in getaddresses(message.get_all(header, []))}
    if customer_email.lower() not in addresses:
        raise ValueError(f"The email's {header} address does not match this inquiry's customer.")
    subject = str(message.get("Subject", "")).strip()
    part = message.get_body(preferencelist=("plain",))
    if not subject or len(subject) > 200 or not part:
        raise ValueError("Email needs a subject up to 200 characters and plain text. Attachments are not imported.")
    try:
        summary = part.get_content().strip()
        occurred_at = parsedate_to_datetime(str(message.get("Date", "")))
    except ValueError, TypeError, LookupError:
        raise ValueError("Email text or date could not be read.") from None
    if not occurred_at.tzinfo or not 1 <= len(summary) <= 4000:
        raise ValueError("Email needs a timezone-aware date and text up to 4,000 characters.")
    identity = str(message.get("Message-ID", "")).strip() or sha256(body).hexdigest()
    return dict(
        subject=subject,
        summary=summary,
        direction=direction,
        occurred_at=occurred_at.astimezone(UTC),
        source_id="eml:" + sha256(identity.encode()).hexdigest(),
    )
