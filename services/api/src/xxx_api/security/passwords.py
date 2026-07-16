"""Argon2id password hashing policy."""

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

MIN_PASSWORD_CHARACTERS = 12
MAX_PASSWORD_BYTES = 1024
password_hasher = PasswordHash.recommended()


def validate_password(password: str) -> None:
    """Enforce bounded password input without silently normalizing it."""
    if len(password) < MIN_PASSWORD_CHARACTERS:
        raise ValueError(f"password must contain at least {MIN_PASSWORD_CHARACTERS} characters")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError("password is too long")


def hash_password(password: str) -> str:
    """Validate and hash a password using the recommended Argon2id parameters."""
    validate_password(password)
    return password_hasher.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    """Return false for a mismatch or an unsupported/corrupt stored hash."""
    try:
        return password_hasher.verify(password, encoded_hash)
    except (UnknownHashError, ValueError):
        return False
