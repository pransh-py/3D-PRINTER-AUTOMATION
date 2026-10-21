"""Validated application configuration."""

from functools import lru_cache
from os import environ
from pathlib import Path
from typing import Literal, cast

from pydantic import AnyHttpUrl, EmailStr, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
AnalysisSandboxMode = Literal["process", "bubblewrap"]


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
    mfa_encryption_secret: SecretStr = SecretStr(
        "development-only-mfa-encryption-secret-change-before-production"
    )
    mfa_issuer: str = "xxx"
    mfa_challenge_ttl_seconds: int = Field(default=300, ge=120, le=600)
    recent_owner_mfa_ttl_seconds: int = Field(default=600, ge=300, le=1800)
    access_token_ttl_seconds: int = Field(default=900, ge=300, le=3600)
    refresh_token_ttl_days: int = Field(default=30, ge=1, le=90)
    max_active_sessions_per_user: int = Field(default=10, ge=1, le=50)
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_socket_timeout_seconds: float = Field(default=1.0, gt=0, le=5)
    analysis_stream_name: str = Field(
        default="xxx:analysis",
        pattern=r"^[a-z0-9:_-]{3,64}$",
    )
    analysis_consumer_group: str = Field(
        default="xxx-analysis-workers",
        pattern=r"^[a-z0-9:_-]{3,64}$",
    )
    analysis_lease_seconds: int = Field(default=600, ge=120, le=3600)
    analysis_max_attempts: int = Field(default=3, ge=1, le=10)
    analysis_validator_command: str = "xxx-analyzer"
    analysis_validator_timeout_seconds: int = Field(default=60, ge=5, le=300)
    analysis_sandbox_mode: AnalysisSandboxMode = "process"
    analysis_bubblewrap_command: str = "bwrap"
    analysis_slicer_command: Path | None = None
    analysis_slicer_version: str | None = Field(default=None, min_length=1, max_length=64)
    analysis_slicer_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    analysis_profile_directory: Path | None = None
    analysis_preset_manifest: Path | None = None
    analysis_profile_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    analysis_material_code: str | None = Field(default=None, pattern=r"^[a-z0-9-]{1,32}$")
    analysis_slicer_timeout_seconds: int = Field(default=240, ge=10, le=600)
    storage_endpoint_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:9000")
    storage_backend: Literal["s3", "local"] = "s3"
    storage_local_directory: Path | None = None
    storage_region: str = Field(default="us-east-1", min_length=1, max_length=64)
    storage_bucket: str = Field(
        default="xxx-private-models",
        pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$",
    )
    storage_access_key: SecretStr = SecretStr("development-minio")
    storage_secret_key: SecretStr = SecretStr("development-minio-secret")
    upload_url_ttl_seconds: int = Field(default=600, ge=120, le=1800)
    max_model_file_bytes: int = Field(default=100 * 1024 * 1024, ge=1024, le=500 * 1024 * 1024)
    max_models_per_quote: int = Field(default=5, ge=1, le=10)
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
    whatsapp_otp_enabled: bool = False
    whatsapp_otp_sender_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:3201")
    whatsapp_otp_sender_api_key: SecretStr | None = None
    whatsapp_otp_timeout_seconds: float = Field(default=20, gt=0, le=30)
    workflow_notifications_enabled: bool = False
    printer_dispatch_enabled: bool = False
    notification_max_attempts: int = Field(default=5, ge=1, le=10)
    email_verification_ttl_hours: int = Field(default=24, ge=1, le=72)
    password_reset_ttl_minutes: int = Field(default=30, ge=10, le=60)
    secure_cookies: bool = False
    razorpay_enabled: bool = False
    razorpay_mode: Literal["test", "live"] = "test"
    razorpay_checkout_name: str | None = Field(default=None, min_length=1, max_length=120)
    razorpay_key_id: str | None = Field(default=None, pattern=r"^rzp_(test|live)_[A-Za-z0-9]+$")
    razorpay_key_secret: SecretStr | None = None
    razorpay_webhook_secret: SecretStr | None = None
    razorpay_timeout_seconds: float = Field(default=10, gt=0, le=20)

    @model_validator(mode="after")
    def validate_production_safety(self) -> "Settings":
        """Refuse configuration that would weaken production boundaries."""
        if self.whatsapp_otp_enabled:
            if self.environment == "production":
                raise ValueError("local-only sender not approved for production")
            url = self.whatsapp_otp_sender_url
            if (url.scheme != "http" or url.host != "127.0.0.1" or url.path not in {None, "/"}
                    or url.username or url.password or url.query or url.fragment):
                raise ValueError("WhatsApp OTP requires a fixed loopback HTTP sender origin")
            key = self.whatsapp_otp_sender_api_key
            if key is None or len(key.get_secret_value().encode()) < 32 or key in {
                self.jwt_signing_secret, self.token_hash_secret, self.mfa_encryption_secret
            }:
                raise ValueError("WhatsApp OTP requires a separate strong sender key")
        if self.storage_backend == "local":
            if self.environment not in {"development", "test"}:
                raise ValueError("local model storage is only for development/test")
            if not self.storage_local_directory or not self.storage_local_directory.is_absolute():
                raise ValueError("local model storage requires an absolute private directory")
            loopback = {"127.0.0.1", "localhost", "::1", "[::1]"}
            if self.public_web_url.host not in loopback or any(
                AnyHttpUrl(origin).host not in loopback for origin in self.allowed_origins
            ):
                raise ValueError("local model storage requires loopback-only web origins")
            directory = self.storage_local_directory.resolve()
            if directory in {Path("/"), Path.home(), Path.cwd()} or "public" in directory.parts:
                raise ValueError("local model storage requires a dedicated non-public directory")
        if self.razorpay_enabled:
            if (
                not self.razorpay_key_id
                or not self.razorpay_key_secret
                or not self.razorpay_webhook_secret
                or not self.razorpay_checkout_name
            ):
                raise ValueError("Razorpay requires key ID, secrets and an approved Checkout name")
            if not self.razorpay_checkout_name.strip() or any(
                ord(char) < 32 for char in self.razorpay_checkout_name
            ):
                raise ValueError("Razorpay Checkout name cannot be blank or contain controls")
            if not self.razorpay_key_id.startswith(f"rzp_{self.razorpay_mode}_"):
                raise ValueError("Razorpay key ID does not match the configured mode")
            if any(
                len(secret.get_secret_value().encode()) < 16
                for secret in (self.razorpay_key_secret, self.razorpay_webhook_secret)
            ):
                raise ValueError("Razorpay secrets must be at least 16 bytes")
            if self.razorpay_key_secret == self.razorpay_webhook_secret:
                raise ValueError("Razorpay API and webhook secrets must be distinct")
            if self.environment == "production" and self.razorpay_mode != "live":
                raise ValueError("Test payments cannot be enabled in production")
            if self.environment in {"development", "test"} and self.razorpay_mode == "live":
                raise ValueError("Live payments cannot be enabled in local or test environments")
        slicer_fields = (
            self.analysis_slicer_command,
            self.analysis_slicer_version,
            self.analysis_slicer_sha256,
        )
        profile_fields = (
            self.analysis_profile_directory,
            self.analysis_profile_sha256,
            self.analysis_material_code,
        )
        if any(value is not None for value in (*slicer_fields, *profile_fields)):
            if any(value is None for value in slicer_fields) or (
                self.analysis_preset_manifest is None
                and any(value is None for value in profile_fields)
            ):
                raise ValueError(
                    "slicing requires executable, version, profiles, hash and material"
                )
            if not self.analysis_slicer_command or not self.analysis_slicer_command.is_absolute():
                raise ValueError("slicer executable must be an absolute reviewed path")
            if self.analysis_preset_manifest is None and (
                not self.analysis_profile_directory
                or not self.analysis_profile_directory.is_absolute()
            ):
                raise ValueError("profile directory must be an absolute reviewed path")
            if self.analysis_preset_manifest and not self.analysis_preset_manifest.is_absolute():
                raise ValueError("preset manifest must be an absolute reviewed path")
            if (
                self.analysis_lease_seconds
                < self.max_models_per_quote * self.analysis_slicer_timeout_seconds + 120
            ):
                raise ValueError("analysis lease must cover all slicing timeouts plus validation")
        if self.environment == "production":
            jwt_secret = self.jwt_signing_secret.get_secret_value()
            token_secret = self.token_hash_secret.get_secret_value()
            mfa_secret = self.mfa_encryption_secret.get_secret_value()
            storage_access_key = self.storage_access_key.get_secret_value()
            storage_secret_key = self.storage_secret_key.get_secret_value()
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
            if mfa_secret.startswith("development-only"):
                raise ValueError("production MFA encryption secret is not configured")
            auth_secrets = (jwt_secret, token_secret, mfa_secret)
            if any(len(secret.encode("utf-8")) < 32 for secret in auth_secrets):
                raise ValueError("production authentication secrets must be at least 32 bytes")
            if len(set(auth_secrets)) != len(auth_secrets):
                raise ValueError("authentication secrets must be distinct")
            if self.public_web_url.scheme != "https":
                raise ValueError("production public web URL must use HTTPS")
            if self.storage_endpoint_url.scheme != "https":
                raise ValueError("production storage endpoint must use HTTPS")
            if storage_access_key.startswith("development-") or storage_secret_key.startswith(
                "development-"
            ):
                raise ValueError("production object-storage credentials are not configured")
            if not Path(self.analysis_validator_command).is_absolute():
                raise ValueError("production analysis validator command must be an absolute path")
            if self.analysis_sandbox_mode != "bubblewrap":
                raise ValueError("production analysis sandbox must use bubblewrap isolation")
            if not Path(self.analysis_bubblewrap_command).is_absolute():
                raise ValueError("production bubblewrap command must be an absolute path")
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
        if not self.mfa_issuer.strip() or len(self.mfa_issuer) > 64:
            raise ValueError("MFA issuer must contain between 1 and 64 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one validated settings object per process."""
    return load_settings()


def load_settings() -> Settings:
    """The dedicated local launcher supplies a complete environment, not a repo .env."""
    # pydantic-settings accepts this runtime option; its generated mypy signature omits it.
    return Settings(  # type: ignore[call-arg]
        _env_file=None if environ.get("PRINTFLOW_IGNORE_DOTENV") == "1" else ".env"
    )
