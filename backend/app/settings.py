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


@lru_cache
def get_settings() -> Settings:
    return Settings()
