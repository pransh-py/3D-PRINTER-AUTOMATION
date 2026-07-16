"""Email identity normalization tests."""

import pytest

from xxx_api.security.email import normalize_email


def test_normalize_email_trims_and_casefolds() -> None:
    assert normalize_email("  Buyer@Example.COM  ") == "buyer@example.com"


def test_normalize_email_rejects_invalid_address() -> None:
    with pytest.raises(ValueError, match="invalid email address"):
        normalize_email("not an address")
