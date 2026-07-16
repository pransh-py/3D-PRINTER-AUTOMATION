"""Validated application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
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
    database_url: str = "sqlite+aiosqlite:///./xxx-development.db"
    jwt_issuer: str = "xxx-api"
    jwt_audience: str = "xxx-web"
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_signing_secret: SecretStr = SecretStr(
        "development-only-jwt-secret-change-before-production"
    )
    token_hash_secret: SecretStr = SecretStr(
        "development-only-token-secret-change-before-production"
    )
    access_token_ttl_seconds: int = Field(default=900, ge=300, le=3600)
    refresh_token_ttl_days: int = Field(default=30, ge=1, le=90)
    email_verification_ttl_hours: int = Field(default=24, ge=1, le=72)
    password_reset_ttl_minutes: int = Field(default=30, ge=10, le=60)
    secure_cookies: bool = False

    @model_validator(mode="after")
    def validate_production_safety(self) -> "Settings":
        """Refuse configuration that would weaken production boundaries."""
        if self.environment == "production":
            jwt_secret = self.jwt_signing_secret.get_secret_value()
            token_secret = self.token_hash_secret.get_secret_value()
            if self.debug:
                raise ValueError("debug must be disabled in production")
            if "*" in self.allowed_origins:
                raise ValueError("wildcard CORS origins are forbidden in production")
            if any(origin.startswith("http://") for origin in self.allowed_origins):
                raise ValueError("production CORS origins must use HTTPS")
            if not self.secure_cookies:
                raise ValueError("secure cookies must be enabled in production")
            if jwt_secret.startswith("development-only"):
                raise ValueError("production JWT signing secret is not configured")
            if token_secret.startswith("development-only"):
                raise ValueError("production token hash secret is not configured")
            if len(jwt_secret.encode("utf-8")) < 32 or len(token_secret.encode("utf-8")) < 32:
                raise ValueError("production authentication secrets must be at least 32 bytes")
            if jwt_secret == token_secret:
                raise ValueError("JWT signing and token hash secrets must be distinct")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one validated settings object per process."""
    return Settings()
