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
    MFA_LOGIN = "mfa_login"


class MfaMethodKind(StrEnum):
    """Supported second-factor methods."""

    TOTP = "totp"


class AuditEventType(StrEnum):
    """Reviewed security-event names stored in the append-only audit log."""

    BUYER_REGISTERED = "identity.buyer_registered"
    EMAIL_VERIFIED = "identity.email_verified"
    SESSION_CREATED = "identity.session_created"
    SESSION_REVOKED = "identity.session_revoked"
    REFRESH_REUSE_DETECTED = "identity.refresh_reuse_detected"
    PASSWORD_RESET = "identity.password_reset"
    OWNER_PROVISIONED = "identity.owner_provisioned"
    OWNER_MFA_CHALLENGE_ISSUED = "identity.owner_mfa_challenge_issued"
    OWNER_MFA_AUTHENTICATED = "identity.owner_mfa_authenticated"
    OWNER_MFA_ENROLLMENT_STARTED = "identity.owner_mfa_enrollment_started"
    OWNER_MFA_ENABLED = "identity.owner_mfa_enabled"
    OWNER_MFA_RESET = "identity.owner_mfa_reset"
