"""TOTP encryption, replay, and recovery-code primitive tests."""

from datetime import UTC, datetime
from uuid import uuid4

import pyotp
import pytest

from xxx_api.config import Settings
from xxx_api.security.mfa import (
    InvalidMfaSecretError,
    decrypt_totp_secret,
    digest_recovery_code,
    encrypt_totp_secret,
    generate_recovery_codes,
    generate_totp_secret,
    matching_totp_counter,
)


def test_totp_secret_is_record_bound_and_authenticated() -> None:
    settings = Settings(environment="test")
    user_id = uuid4()
    method_id = uuid4()
    secret = generate_totp_secret()
    encrypted = encrypt_totp_secret(secret, user_id, method_id, settings)

    assert secret not in encrypted
    assert decrypt_totp_secret(encrypted, user_id, method_id, settings) == secret
    with pytest.raises(InvalidMfaSecretError):
        decrypt_totp_secret(encrypted, user_id, uuid4(), settings)


def test_totp_accepts_one_step_drift_and_rejects_replay() -> None:
    secret = generate_totp_secret()
    checked_at = datetime(2026, 7, 17, 12, 0, 30, tzinfo=UTC)
    current_counter = int(checked_at.timestamp()) // 30
    previous_code = pyotp.TOTP(secret).at((current_counter - 1) * 30)

    matched = matching_totp_counter(secret, previous_code, now=checked_at)

    assert matched == current_counter - 1
    assert (
        matching_totp_counter(
            secret,
            previous_code,
            now=checked_at,
            last_used_counter=matched,
        )
        is None
    )


def test_recovery_codes_are_unique_and_normalized_before_digest() -> None:
    settings = Settings(environment="test")
    codes = generate_recovery_codes()

    assert len(codes) == 10
    assert len(set(codes)) == 10
    assert all(len(code.replace("-", "")) == 16 for code in codes)
    assert digest_recovery_code(codes[0], settings) == digest_recovery_code(
        codes[0].lower().replace("-", ""),
        settings,
    )
