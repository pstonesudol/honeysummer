"""Email-safe, autoescaped templates using the Honey Summer website palette."""

from base64 import b64encode
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .settings import get_settings

_templates = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent.parent / "templates" / "emails"),
    autoescape=select_autoescape(["html"]),
)

LOGO_CONTENT_ID = "honey-summer-logo"


@lru_cache
def logo_attachment() -> dict:
    """Embed the website logo so staging authentication cannot block it."""
    logo = Path(__file__).resolve().parent.parent / "templates" / "emails" / "honey-summer-logo.png"
    return {
        "filename": "honey-summer-logo.png",
        "content": b64encode(logo.read_bytes()).decode("ascii"),
        "content_type": "image/png",
        "content_id": LOGO_CONTENT_ID,
    }


def render_email(*, title: str, body: str, order: dict | None = None, secure_links: bool = False) -> str:
    """Render branded HTML without changing the plain-text delivery fallback."""
    settings = get_settings()
    return _templates.get_template("order.html" if order is not None else "message.html").render(
        title=title,
        preheader=body.split("\n", 1)[0],
        paragraphs=body.split("\n\n"),
        logo_url=f"cid:{LOGO_CONTENT_ID}",
        site_url=settings.public_origin.rstrip("/"),
        contact_email=settings.inquiry_notification_email,
        order=order,
        secure_links=secure_links,
    )
