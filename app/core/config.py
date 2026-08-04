"""Application settings loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for QualiTrack."""

    app_name: str = "QualiTrack"
    app_description: str = "Manufacturing Quality Inspection & Defect Analytics Platform"
    app_version: str = "0.1.0"
    debug: bool = False
    database_url: str = "sqlite:///./qualitrack.db"
    secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()
