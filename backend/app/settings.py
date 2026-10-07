"""Application settings for the Sanic backend.

During the Django → Sanic migration these read the same environment as the
Django app (via ``AliasChoices``) so both servers can run against one ``.env``.
The cutover in phase 4g renames the variables to their unprefixed names.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    debug: bool = Field(default=False, validation_alias=AliasChoices("DEBUG", "DJANGO_DEBUG"))
    secret_key: str = Field(
        default="insecure-local-development-key",
        validation_alias=AliasChoices("SECRET_KEY", "DJANGO_SECRET_KEY"),
    )
    database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/honeysummer",
        validation_alias="DATABASE_URL",
    )
    media_root: Path = Field(default=BASE_DIR / "media", validation_alias="MEDIA_ROOT")
    media_url: str = Field(default="/media", validation_alias="MEDIA_URL")

    resend_api_key: str = Field(default="", validation_alias="RESEND_API_KEY")
    default_from_email: str = Field(
        default="Honey Summer <hello@hellohoneysummer.com>",
        validation_alias="DEFAULT_FROM_EMAIL",
    )
    inquiry_notification_email: str = Field(
        default="hello@hellohoneysummer.com",
        validation_alias="INQUIRY_NOTIFICATION_EMAIL",
    )

    stripe_secret_key: str = Field(default="", validation_alias="STRIPE_SECRET_KEY")
    stripe_webhook_secret: str = Field(default="", validation_alias="STRIPE_WEBHOOK_SECRET")
    checkout_success_url: str = Field(
        default="http://localhost:3000/wholesale?checkout=success",
        validation_alias="CHECKOUT_SUCCESS_URL",
    )
    checkout_cancel_url: str = Field(
        default="http://localhost:3000/wholesale?checkout=cancelled",
        validation_alias="CHECKOUT_CANCEL_URL",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
