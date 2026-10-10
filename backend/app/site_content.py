"""Owner-editable public text; an empty record preserves the current storefront."""

from __future__ import annotations

from urllib.parse import urlparse

FIELDS = {
    "location": 160,
    "serviceArea": 500,
    "email": 254,
    "phone": 40,
    "instagram": 500,
    "pickupLocation": 300,
    "pickupWindow": 300,
    "pickupNote": 500,
    "announcementFallback": 200,
    "homeIntro": 2000,
    "aboutIntro": 2000,
    "weddingsIntro": 2000,
    "orderIntro": 2000,
    "contactIntro": 2000,
    "wholesaleIntro": 2000,
}

PHOTO_SLOTS = {
    "home": "Home hero",
    "about": "About hero",
    "weddings": "Weddings hero",
    "order": "Order flowers hero",
    "contact": "Contact hero",
    "wholesale": "Wholesale hero",
    "homeFlowers": "Home flowers card",
    "homeWeddings": "Home weddings card",
    "homeWholesale": "Home wholesale card",
}


def validate_content(form) -> dict:
    """Validate and normalize owner-edited storefront content."""
    result = {}
    for field, limit in FIELDS.items():
        value = str(form.get(field, "")).strip()
        if len(value) > limit:
            raise ValueError(f"{field} must be {limit} characters or fewer.")
        result[field] = value
    if result["email"] and ("@" not in result["email"] or "\n" in result["email"]):
        raise ValueError("Enter a valid contact email address.")
    if result["instagram"]:
        parsed = urlparse(result["instagram"])
        if parsed.scheme != "https" or parsed.hostname not in ("instagram.com", "www.instagram.com"):
            raise ValueError("Instagram must be an https://instagram.com link.")
    faq = []
    for index in range(1, 9):
        question = str(form.get(f"faq_question_{index}", "")).strip()
        answer = str(form.get(f"faq_answer_{index}", "")).strip()
        if question or answer:
            if not question or not answer or len(question) > 200 or len(answer) > 1000:
                raise ValueError(f"FAQ {index} needs a question (up to 200 characters) and answer (up to 1,000).")
            faq.append(dict(question=question, answer=answer))
    result["faq"] = faq
    return result
