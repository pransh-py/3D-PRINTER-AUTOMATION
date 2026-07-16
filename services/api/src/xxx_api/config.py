"""Validated application configuration."""

from functools import lru_cache
from typing import Literal, cast

from pydantic import AnyHttpUrl, EmailStr, Field, SecretStr, model_validator
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
    max_active_sessions_per_user: int = Field(default=10, ge=1, le=50)
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_socket_timeout_seconds: float = Field(default=1.0, gt=0, le=5)
    public_web_url: AnyHttpUrl = AnyHttpUrl("http://localhost:3000")
    email_sender_address: EmailStr = cast(EmailStr, "no-reply@example.com")
    email_sender_name: str = "xxx"
    smtp_host: str = "127.0.0.1"
    smtp_port: int = Field(default=1025, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = False
    smtp_use_tls: bool = False
    smtp_timeout_seconds: float = Field(default=10.0, gt=0, le=30)
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
            if self.public_web_url.scheme != "https":
                raise ValueError("production public web URL must use HTTPS")
            if self.email_sender_address == "no-reply@example.com":
                raise ValueError("production email sender address is not configured")
            if self.smtp_host in {"127.0.0.1", "localhost"} and self.smtp_port == 1025:
                raise ValueError("production SMTP provider is not configured")
        if "\r" in self.email_sender_name or "\n" in self.email_sender_name:
            raise ValueError("email sender name cannot contain line breaks")
        if self.smtp_starttls and self.smtp_use_tls:
            raise ValueError("SMTP STARTTLS and implicit TLS cannot both be enabled")
        if bool(self.smtp_username) != bool(self.smtp_password):
            raise ValueError("SMTP username and password must be configured together")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one validated settings object per process."""
    return Settings()
