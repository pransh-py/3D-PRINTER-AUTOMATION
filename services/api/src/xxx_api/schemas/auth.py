"""Public identity API schemas."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from xxx_api.domain.roles import Role


class AuthSchema(BaseModel):
    """Reject unknown fields and expose camelCase browser contracts."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RegisterRequest(AuthSchema):
    """Public buyer registration input."""

    email: EmailStr
    display_name: str = Field(alias="displayName", min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=1024)


class EmailRequest(AuthSchema):
    """Email-only generic account action."""

    email: EmailStr


class TokenRequest(AuthSchema):
    """One-time bearer token submitted in JSON, never a query log."""

    token: str = Field(min_length=32, max_length=512)


class LoginRequest(AuthSchema):
    """Email and password credentials."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class MfaLoginRequest(AuthSchema):
    """Short-lived login challenge plus TOTP or recovery proof."""

    challenge: str = Field(min_length=32, max_length=512)
    code: str = Field(min_length=6, max_length=64)


class MfaChallengeResponse(AuthSchema):
    """Owner password step result that intentionally carries no session."""

    mfa_required: bool = Field(alias="mfaRequired", default=True)
    challenge: str


class OwnerMfaStatusResponse(AuthSchema):
    """Owner MFA enrollment status without secret material."""

    enabled: bool


class OwnerMfaEnrollmentRequest(AuthSchema):
    """Password reauthentication before issuing enrollment material."""

    current_password: str = Field(alias="currentPassword", min_length=1, max_length=1024)


class OwnerMfaEnrollmentResponse(AuthSchema):
    """Enrollment material returned only while MFA is pending."""

    secret: str
    provisioning_uri: str = Field(alias="provisioningUri")


class OwnerMfaConfirmationRequest(AuthSchema):
    """TOTP proof used to activate the pending method."""

    code: str = Field(min_length=6, max_length=64)


class OwnerMfaConfirmationResponse(AuthSchema):
    """Recovery codes returned once at successful activation."""

    message: str
    recovery_codes: list[str] = Field(alias="recoveryCodes")


class ResetPasswordRequest(AuthSchema):
    """One-time token and replacement password."""

    token: str = Field(min_length=32, max_length=512)
    new_password: str = Field(alias="newPassword", min_length=12, max_length=1024)


class MessageResponse(AuthSchema):
    """Stable generic operation result."""

    message: str


class AuthenticatedUserResponse(AuthSchema):
    """Safe current-user fields; no token or credential state."""

    id: UUID
    email: EmailStr
    display_name: str = Field(alias="displayName")
    role: Role
