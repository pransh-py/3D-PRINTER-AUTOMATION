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
        )
