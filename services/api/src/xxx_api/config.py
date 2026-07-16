"""Validated application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="XXX_",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "xxx API"
    environment: Environment = "development"
    debug: bool = False
    log_level: LogLevel = "INFO"
    api_prefix: str = "/api/v1"
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    @model_validator(mode="after")
    def validate_production_safety(self) -> "Settings":
        """Refuse configuration that would weaken production boundaries."""
        if self.environment == "production":
            if self.debug:
                raise ValueError("debug must be disabled in production")
            if "*" in self.allowed_origins:
                raise ValueError("wildcard CORS origins are forbidden in production")
            if any(origin.startswith("http://") for origin in self.allowed_origins):
                raise ValueError("production CORS origins must use HTTPS")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one validated settings object per process."""
    return Settings()
