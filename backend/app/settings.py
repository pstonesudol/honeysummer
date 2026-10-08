"""Application settings for the Sanic backend.

Environment variables are unprefixed (``SECRET_KEY``, ``DEBUG``,
``DATABASE_URL``, …) and read from the process or ``backend/.env``.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    debug: bool = False
    secret_key: str = "insecure-local-development-key"
    database_url: str = "postgresql://postgres:postgres@localhost:5432/honeysummer"
    media_root: Path = BASE_DIR / "media"
    media_url: str = "/media"

    resend_api_key: str = ""
    default_from_email: str = "Honey Summer <hello@hellohoneysummer.com>"
    inquiry_notification_email: str = "hello@hellohoneysummer.com"

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    checkout_success_url: str = "http://localhost:3000/wholesale?checkout=success"
    checkout_cancel_url: str = "http://localhost:3000/wholesale?checkout=cancelled"

    retail_checkout_success_url: str = "http://localhost:3000/order-flowers?checkout=success"
    retail_checkout_cancel_url: str = "http://localhost:3000/order-flowers?checkout=cancelled"


@lru_cache
def get_settings() -> Settings:
    return Settings()
