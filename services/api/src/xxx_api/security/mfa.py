"""Owner TOTP encryption, validation, and recovery-code primitives."""

from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, datetime
from hashlib import sha256
from secrets import token_bytes, token_hex
from uuid import UUID

import pyotp
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pyotp.utils import strings_equal

from xxx_api.config import Settings
from xxx_api.security.tokens import digest_opaque_token

TOTP_DIGITS = 6
TOTP_INTERVAL_SECONDS = 30
TOTP_SECRET_LENGTH = 32
RECOVERY_CODE_COUNT = 10


class InvalidMfaSecretError(ValueError):
    """Encrypted MFA material could not be authenticated or decoded."""


def _encryption_key(settings: Settings) -> bytes:
    configured = settings.mfa_encryption_secret.get_secret_value().encode("utf-8")
    return sha256(configured).digest()


def _associated_data(user_id: UUID, method_id: UUID) -> bytes:
    return f"xxx:mfa:v1:{user_id}:{method_id}".encode("ascii")


def encrypt_totp_secret(secret: str, user_id: UUID, method_id: UUID, settings: Settings) -> str:
    """Encrypt one TOTP secret with record-bound AES-256-GCM."""
    nonce = token_bytes(12)
    ciphertext = AESGCM(_encryption_key(settings)).encrypt(
        nonce,
        secret.encode("ascii"),
        _associated_data(user_id, method_id),
    )
    return urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_totp_secret(
    encrypted_secret: str,
    user_id: UUID,
    method_id: UUID,
    settings: Settings,
) -> str:
    """Authenticate and decrypt one record-bound TOTP secret."""
    try:
        combined = urlsafe_b64decode(encrypted_secret.encode("ascii"))
        if len(combined) < 29:
            raise ValueError("encrypted MFA value is too short")
        nonce, ciphertext = combined[:12], combined[12:]
        plaintext = AESGCM(_encryption_key(settings)).decrypt(
            nonce,
            ciphertext,
            _associated_data(user_id, method_id),
        )
        return plaintext.decode("ascii")
    except (InvalidTag, UnicodeError, ValueError) as error:
        raise InvalidMfaSecretError("encrypted MFA value is invalid") from error


def generate_totp_secret() -> str:
    """Generate a 160-bit Base32 TOTP secret."""
    return pyotp.random_base32(length=TOTP_SECRET_LENGTH)


def totp_provisioning_uri(secret: str, email: str, issuer: str) -> str:
    """Create a standard authenticator-app provisioning URI."""
    return pyotp.TOTP(
        secret,
        digits=TOTP_DIGITS,
        interval=TOTP_INTERVAL_SECONDS,
    ).provisioning_uri(name=email, issuer_name=issuer)


def matching_totp_counter(
    secret: str,
    code: str,
    *,
    now: datetime | None = None,
    last_used_counter: int | None = None,
) -> int | None:
    """Return one unused matching counter within one adjacent time step."""
    if len(code) != TOTP_DIGITS or not code.isascii() or not code.isdigit():
        return None
    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    current_counter = int(checked_at.timestamp()) // TOTP_INTERVAL_SECONDS
    totp = pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_INTERVAL_SECONDS)
    for counter in (current_counter - 1, current_counter, current_counter + 1):
        if counter < 0 or (last_used_counter is not None and counter <= last_used_counter):
            continue
        if strings_equal(totp.at(counter * TOTP_INTERVAL_SECONDS), code):
            return counter
    return None


def generate_recovery_codes() -> tuple[str, ...]:
    """Generate high-entropy codes returned only during enrollment."""
    codes: list[str] = []
    for _ in range(RECOVERY_CODE_COUNT):
        compact = token_hex(8).upper()
        codes.append("-".join(compact[index : index + 4] for index in range(0, 16, 4)))
    return tuple(codes)


def normalize_recovery_code(code: str) -> str:
    """Normalize only the documented separators and ASCII case."""
    return code.strip().replace("-", "").upper()


def digest_recovery_code(code: str, settings: Settings) -> str:
    """Key and purpose-bind a normalized recovery code for storage."""
    return digest_opaque_token(f"mfa-recovery:{normalize_recovery_code(code)}", settings)
