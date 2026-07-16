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
    settings = Settings(environment="production", allowed_origins=["https://example.com"])

    assert settings.debug is False
