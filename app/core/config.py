"""Application configuration via pydantic-settings.

All settings are loaded from environment variables or .env file.
Never use bare os.getenv() anywhere else in the codebase.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = "postgresql+psycopg://eupublicode:eupublicode@db:5432/eupublicode"

    # GitHub API
    github_token: str = ""

    # Developers Italia API
    developers_italia_base_url: str = "https://api.developers.italia.it/v1/software"

    # Scheduler
    ingest_interval_seconds: int = 86400

    # CORS
    allowed_origins: list[str] = ["http://localhost:8501"]

    # Application
    app_title: str = "EU PubliCodeHealth"
    app_version: str = "0.1.0"
    debug: bool = False

    @field_validator("developers_italia_base_url")
    @classmethod
    def validate_api_url_https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("API base URL must use HTTPS")
        return v

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance (singleton)."""
    return Settings()
