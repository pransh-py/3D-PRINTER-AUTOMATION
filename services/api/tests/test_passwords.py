"""Password policy and hashing tests."""

import pytest

from xxx_api.security.passwords import hash_password, validate_password, verify_password


def test_password_hash_is_argon2_and_verifies() -> None:
    encoded = hash_password("correct horse battery staple")

    assert encoded.startswith("$argon2")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("incorrect horse battery staple", encoded)


def test_password_policy_rejects_short_values() -> None:
    with pytest.raises(ValueError, match="at least 12"):
        validate_password("too-short")


def test_corrupt_password_hash_fails_closed() -> None:
    assert not verify_password("correct horse battery staple", "not-a-password-hash")
