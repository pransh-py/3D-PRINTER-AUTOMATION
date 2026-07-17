"""Configuration safety tests."""

import pytest
from pydantic import ValidationError

from xxx_api.config import Settings


def test_production_rejects_debug() -> None:
    with pytest.raises(ValidationError, match="debug must be disabled"):
        Settings(environment="production", debug=True, allowed_origins=["https://example.com"])


def test_production_rejects_wildcard_origin() -> None:
    with pytest.raises(ValidationError, match="wildcard CORS origins"):
        Settings(environment="production", allowed_origins=["*"])


def test_production_rejects_insecure_origin() -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        Settings(environment="production", allowed_origins=["http://example.com"])


def test_production_accepts_https_origin() -> None:
    settings = Settings(
        environment="production",
        allowed_origins=["https://example.com"],
        secure_cookies=True,
        jwt_signing_secret="production-jwt-signing-secret-1234567890",
        token_hash_secret="production-token-hash-secret-0987654321",
        mfa_encryption_secret="production-mfa-encryption-secret-2468135790",
        storage_endpoint_url="https://storage.example.org",
        storage_access_key="production-storage-access",
        storage_secret_key="production-storage-secret",
        analysis_validator_command="/opt/xxx/bin/xxx-analyzer",
        analysis_sandbox_mode="bubblewrap",
        analysis_bubblewrap_command="/usr/bin/bwrap",
        public_web_url="https://example.com",
        email_sender_address="no-reply@example.org",
        smtp_host="smtp.example.org",
        smtp_port=587,
        smtp_starttls=True,
    )

    assert settings.debug is False


def test_production_rejects_development_secrets() -> None:
    with pytest.raises(ValidationError, match="JWT signing secret"):
        Settings(
            environment="production",
            allowed_origins=["https://example.com"],
            secure_cookies=True,
        )


def test_production_rejects_shared_authentication_secret() -> None:
    shared_secret = "one-production-secret-must-not-do-two-jobs"

    with pytest.raises(ValidationError, match="must be distinct"):
        Settings(
            environment="production",
            allowed_origins=["https://example.com"],
            secure_cookies=True,
            jwt_signing_secret=shared_secret,
            token_hash_secret=shared_secret,
            mfa_encryption_secret="production-mfa-encryption-secret-2468135790",
            public_web_url="https://example.com",
            email_sender_address="no-reply@example.org",
            smtp_host="smtp.example.org",
            smtp_port=587,
            smtp_starttls=True,
        )


def test_production_rejects_mfa_secret_shared_with_token_secret() -> None:
    shared_secret = "production-shared-authentication-secret-123456"
    with pytest.raises(ValidationError, match="authentication secrets must be distinct"):
        Settings(
            environment="production",
            allowed_origins=["https://example.com"],
            secure_cookies=True,
            jwt_signing_secret="production-jwt-signing-secret-1234567890",
            token_hash_secret=shared_secret,
            mfa_encryption_secret=shared_secret,
            public_web_url="https://example.com",
            email_sender_address="no-reply@example.org",
            smtp_host="smtp.example.org",
            smtp_port=587,
            smtp_starttls=True,
        )


def test_production_rejects_development_mfa_encryption_secret() -> None:
    with pytest.raises(ValidationError, match="MFA encryption secret"):
        Settings(
            environment="production",
            allowed_origins=["https://example.com"],
            secure_cookies=True,
            jwt_signing_secret="production-jwt-signing-secret-1234567890",
            token_hash_secret="production-token-hash-secret-0987654321",
            public_web_url="https://example.com",
            email_sender_address="no-reply@example.org",
            smtp_host="smtp.example.org",
        )


def test_production_rejects_local_email_transport() -> None:
    with pytest.raises(ValidationError, match="SMTP provider"):
        Settings(
            environment="production",
            allowed_origins=["https://example.com"],
            secure_cookies=True,
            jwt_signing_secret="production-jwt-signing-secret-1234567890",
            token_hash_secret="production-token-hash-secret-0987654321",
            mfa_encryption_secret="production-mfa-encryption-secret-2468135790",
            storage_endpoint_url="https://storage.example.org",
            storage_access_key="production-storage-access",
            storage_secret_key="production-storage-secret",
            analysis_validator_command="/opt/xxx/bin/xxx-analyzer",
            analysis_sandbox_mode="bubblewrap",
            analysis_bubblewrap_command="/usr/bin/bwrap",
            public_web_url="https://example.com",
            email_sender_address="no-reply@example.org",
        )


def test_production_rejects_insecure_or_default_object_storage() -> None:
    common = {
        "environment": "production",
        "allowed_origins": ["https://example.com"],
        "secure_cookies": True,
        "jwt_signing_secret": "production-jwt-signing-secret-1234567890",
        "token_hash_secret": "production-token-hash-secret-0987654321",
        "mfa_encryption_secret": "production-mfa-encryption-secret-2468135790",
        "public_web_url": "https://example.com",
        "email_sender_address": "no-reply@example.org",
        "smtp_host": "smtp.example.org",
        "smtp_port": 587,
        "smtp_starttls": True,
    }
    with pytest.raises(ValidationError, match="storage endpoint must use HTTPS"):
        Settings(**common)
    with pytest.raises(ValidationError, match="object-storage credentials"):
        Settings(**common, storage_endpoint_url="https://storage.example.org")


def test_production_requires_absolute_analysis_validator() -> None:
    with pytest.raises(ValidationError, match="validator command must be an absolute path"):
        Settings(
            environment="production",
            allowed_origins=["https://example.com"],
            secure_cookies=True,
            jwt_signing_secret="production-jwt-signing-secret-1234567890",
            token_hash_secret="production-token-hash-secret-0987654321",
            mfa_encryption_secret="production-mfa-encryption-secret-2468135790",
            storage_endpoint_url="https://storage.example.org",
            storage_access_key="production-storage-access",
            storage_secret_key="production-storage-secret",
            public_web_url="https://example.com",
            email_sender_address="no-reply@example.org",
            smtp_host="smtp.example.org",
            smtp_port=587,
            smtp_starttls=True,
        )


def test_production_requires_os_level_analysis_sandbox() -> None:
    common = {
        "environment": "production",
        "allowed_origins": ["https://example.com"],
        "secure_cookies": True,
        "jwt_signing_secret": "production-jwt-signing-secret-1234567890",
        "token_hash_secret": "production-token-hash-secret-0987654321",
        "mfa_encryption_secret": "production-mfa-encryption-secret-2468135790",
        "storage_endpoint_url": "https://storage.example.org",
        "storage_access_key": "production-storage-access",
        "storage_secret_key": "production-storage-secret",
        "analysis_validator_command": "/opt/xxx/bin/xxx-analyzer",
        "public_web_url": "https://example.com",
        "email_sender_address": "no-reply@example.org",
        "smtp_host": "smtp.example.org",
        "smtp_port": 587,
        "smtp_starttls": True,
    }
    with pytest.raises(ValidationError, match="must use bubblewrap isolation"):
        Settings(**common)
    with pytest.raises(ValidationError, match="bubblewrap command must be an absolute path"):
        Settings(**common, analysis_sandbox_mode="bubblewrap")


def test_smtp_tls_modes_are_mutually_exclusive() -> None:
    with pytest.raises(ValidationError, match="cannot both be enabled"):
        Settings(smtp_starttls=True, smtp_use_tls=True)
