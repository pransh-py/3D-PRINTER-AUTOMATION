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
    QUOTE_REQUEST_CREATED = "quote.request_created"
    MODEL_UPLOAD_ISSUED = "quote.model_upload_issued"
    MODEL_UPLOAD_COMPLETED = "quote.model_upload_completed"
    MODEL_UPLOAD_REJECTED = "quote.model_upload_rejected"
    QUOTE_REQUEST_SUBMITTED = "quote.request_submitted"
    ANALYSIS_RUN_QUEUED = "analysis.run_queued"
    ANALYSIS_RUN_STARTED = "analysis.run_started"
    ANALYSIS_RUN_AWAITING_PROFILE = "analysis.run_awaiting_profile"
    ANALYSIS_RUN_SUCCEEDED = "analysis.run_succeeded"
    ANALYSIS_RUN_FAILED = "analysis.run_failed"
