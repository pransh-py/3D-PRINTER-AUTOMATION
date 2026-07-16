"""Authentication-domain states and token purposes."""

from enum import StrEnum


class UserStatus(StrEnum):
    """Account states enforced by authentication policy."""

    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    DISABLED = "disabled"


class OneTimeTokenPurpose(StrEnum):
    """Purposes that cannot be interchanged for a one-time token."""

    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"
