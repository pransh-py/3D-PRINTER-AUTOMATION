"""Transactional singleton-owner provisioning, MFA, and recovery services."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from anyio import to_thread
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from xxx_api.config import Settings
from xxx_api.domain.auth import AuditEventType, MfaMethodKind, OneTimeTokenPurpose, UserStatus
from xxx_api.domain.roles import Role
from xxx_api.models.identity import MfaMethod, MfaRecoveryCode, OneTimeToken, RefreshSession, User
from xxx_api.security.email import normalize_email
from xxx_api.security.mfa import (
    InvalidMfaSecretError,
    decrypt_totp_secret,
    digest_recovery_code,
    encrypt_totp_secret,
    generate_recovery_codes,
    generate_totp_secret,
    matching_totp_counter,
    totp_provisioning_uri,
)
from xxx_api.security.passwords import MAX_PASSWORD_BYTES, hash_password, verify_password
from xxx_api.security.tokens import digest_opaque_token
from xxx_api.services.audit import append_audit_event
from xxx_api.services.auth import AuthenticatedPrincipal, SessionIssue, issue_session_for_user


class OwnerSecurityError(Exception):
    """Base owner-security failure translated by trusted adapters."""


class OwnerAlreadyProvisionedError(OwnerSecurityError):
    """The singleton owner slot is already occupied."""


class OwnerProvisioningConflictError(OwnerSecurityError):
    """The requested owner email belongs to another identity."""


class OwnerAccessDeniedError(OwnerSecurityError):
    """The authenticated identity is not the active primary owner."""


class InvalidOwnerPasswordError(OwnerSecurityError):
    """Owner password reauthentication failed."""


class MfaAlreadyEnabledError(OwnerSecurityError):
    """The owner already has an enabled MFA method."""


class MfaEnrollmentRequiredError(OwnerSecurityError):
    """No pending or enabled owner MFA method is available."""


class InvalidMfaCodeError(OwnerSecurityError):
    """A TOTP, recovery code, or login challenge is invalid or expired."""


class MfaConfigurationError(OwnerSecurityError):
    """Encrypted MFA state cannot be safely used."""


@dataclass(frozen=True, slots=True)
class OwnerMfaEnrollment:
    """TOTP enrollment material returned exactly before confirmation."""

    secret: str
    provisioning_uri: str


@dataclass(frozen=True, slots=True)
class OwnerMfaConfirmation:
    """One-time recovery codes returned when MFA becomes active."""

    recovery_codes: tuple[str, ...]


def _utc_now(now: datetime | None) -> datetime:
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _stored_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _display_name(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > 100:
        raise ValueError("display name must contain between 1 and 100 characters")
    return normalized


async def _password_matches(password: str, encoded_hash: str) -> bool:
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return False
    return await to_thread.run_sync(verify_password, password, encoded_hash)


def _assert_primary_owner(user: User) -> None:
    if (
        user.role is not Role.OWNER
        or user.owner_slot != "primary"
        or user.status is not UserStatus.ACTIVE
    ):
        raise OwnerAccessDeniedError


async def provision_owner(
    session: AsyncSession,
    settings: Settings,
    *,
    email: str,
    display_name: str,
    password: str,
    now: datetime | None = None,
) -> UUID:
    """Occupy the singleton owner slot through a deployment-only adapter."""
    normalized_email = normalize_email(email)
    normalized_name = _display_name(display_name)
    provisioned_at = _utc_now(now)
    existing_owner = await session.scalar(
        select(User.id).where(User.owner_slot == "primary").with_for_update()
    )
    if existing_owner is not None:
        await session.rollback()
        raise OwnerAlreadyProvisionedError
    existing_email = await session.scalar(select(User.id).where(User.email == normalized_email))
    if existing_email is not None:
        await session.rollback()
        raise OwnerProvisioningConflictError

    password_hash = await to_thread.run_sync(hash_password, password)
    owner = User(
        email=normalized_email,
        display_name=normalized_name,
        password_hash=password_hash,
        role=Role.OWNER,
        owner_slot="primary",
        status=UserStatus.ACTIVE,
        email_verified_at=provisioned_at,
        password_changed_at=provisioned_at,
    )
    session.add(owner)
    try:
        await session.flush()
        append_audit_event(
            session,
            AuditEventType.OWNER_PROVISIONED,
            occurred_at=provisioned_at,
            actor_user_id=owner.id,
            target_user_id=owner.id,
            details={"role": Role.OWNER.value},
        )
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise OwnerAlreadyProvisionedError from error
    return owner.id


async def owner_mfa_enabled(session: AsyncSession, user: User) -> bool:
    """Return whether the active primary owner has confirmed TOTP."""
    _assert_primary_owner(user)
    enabled_at = await session.scalar(
        select(MfaMethod.enabled_at).where(MfaMethod.user_id == user.id)
    )
    return enabled_at is not None


async def start_owner_mfa_enrollment(
    session: AsyncSession,
    settings: Settings,
    *,
    principal: AuthenticatedPrincipal,
    current_password: str,
    now: datetime | None = None,
    request_id: str | None = None,
) -> OwnerMfaEnrollment:
    """Reauthenticate and create or replace one pending encrypted TOTP secret."""
    _assert_primary_owner(principal.user)
    if not await _password_matches(current_password, principal.user.password_hash):
        await session.rollback()
        raise InvalidOwnerPasswordError
    started_at = _utc_now(now)
    method = await session.scalar(
        select(MfaMethod).where(MfaMethod.user_id == principal.user.id).with_for_update()
    )
    if method is not None and method.enabled_at is not None:
        await session.rollback()
        raise MfaAlreadyEnabledError

    secret = generate_totp_secret()
    if method is None:
        method = MfaMethod(
            id=uuid4(),
            user_id=principal.user.id,
            kind=MfaMethodKind.TOTP,
            encrypted_secret="pending",
        )
        session.add(method)
    method.encrypted_secret = encrypt_totp_secret(
        secret,
        principal.user.id,
        method.id,
        settings,
    )
    method.enabled_at = None
    method.last_used_counter = None
    await session.execute(
        delete(MfaRecoveryCode).where(MfaRecoveryCode.mfa_method_id == method.id)
    )
    append_audit_event(
        session,
        AuditEventType.OWNER_MFA_ENROLLMENT_STARTED,
        occurred_at=started_at,
        actor_user_id=principal.user.id,
        target_user_id=principal.user.id,
        session_id=principal.refresh_session.id,
        request_id=request_id,
    )
    await session.commit()
    return OwnerMfaEnrollment(
        secret=secret,
        provisioning_uri=totp_provisioning_uri(
            secret,
            principal.user.email,
            settings.mfa_issuer,
        ),
    )


async def confirm_owner_mfa_enrollment(
    session: AsyncSession,
    settings: Settings,
    *,
    principal: AuthenticatedPrincipal,
    code: str,
    now: datetime | None = None,
    request_id: str | None = None,
) -> OwnerMfaConfirmation:
    """Confirm pending TOTP, mark this session MFA-authenticated, and issue recovery codes."""
    _assert_primary_owner(principal.user)
    confirmed_at = _utc_now(now)
    method = await session.scalar(
        select(MfaMethod).where(MfaMethod.user_id == principal.user.id).with_for_update()
    )
    if method is None or method.enabled_at is not None:
        await session.rollback()
        raise MfaEnrollmentRequiredError
    try:
        secret = decrypt_totp_secret(
            method.encrypted_secret,
            method.user_id,
            method.id,
            settings,
        )
    except InvalidMfaSecretError as error:
        await session.rollback()
        raise MfaConfigurationError from error
    counter = matching_totp_counter(secret, code, now=confirmed_at)
    if counter is None:
        await session.rollback()
        raise InvalidMfaCodeError

    method.enabled_at = confirmed_at
    method.last_used_counter = counter
    recovery_codes = generate_recovery_codes()
    for recovery_code in recovery_codes:
        session.add(
            MfaRecoveryCode(
                mfa_method_id=method.id,
                code_digest=digest_recovery_code(recovery_code, settings),
                created_at=confirmed_at,
            )
        )
    current_session = await session.scalar(
        select(RefreshSession)
        .where(RefreshSession.id == principal.refresh_session.id)
        .with_for_update()
    )
    if current_session is None or current_session.revoked_at is not None:
        await session.rollback()
        raise OwnerAccessDeniedError
    current_session.mfa_authenticated_at = confirmed_at
    append_audit_event(
        session,
        AuditEventType.OWNER_MFA_ENABLED,
        occurred_at=confirmed_at,
        actor_user_id=principal.user.id,
        target_user_id=principal.user.id,
        session_id=current_session.id,
        request_id=request_id,
    )
    await session.commit()
    return OwnerMfaConfirmation(recovery_codes=recovery_codes)


async def complete_owner_mfa_login(
    session: AsyncSession,
    settings: Settings,
    *,
    challenge: str,
    code: str,
    user_agent: str | None = None,
    now: datetime | None = None,
    request_id: str | None = None,
) -> SessionIssue:
    """Consume one owner challenge plus TOTP/recovery proof and create a session."""
    authenticated_at = _utc_now(now)
    challenge_digest = digest_opaque_token(challenge, settings)
    token = await session.scalar(
        select(OneTimeToken)
        .where(
            OneTimeToken.token_digest == challenge_digest,
            OneTimeToken.purpose == OneTimeTokenPurpose.MFA_LOGIN,
        )
        .options(selectinload(OneTimeToken.user))
        .with_for_update()
    )
    if (
        token is None
        or token.consumed_at is not None
        or _stored_utc(token.expires_at) <= authenticated_at
        or token.user.status is not UserStatus.ACTIVE
        or token.user.role is not Role.OWNER
        or token.user.owner_slot != "primary"
    ):
        await session.rollback()
        raise InvalidMfaCodeError
    method = await session.scalar(
        select(MfaMethod).where(MfaMethod.user_id == token.user_id).with_for_update()
    )
    if method is None or method.enabled_at is None:
        await session.rollback()
        raise InvalidMfaCodeError
    try:
        secret = decrypt_totp_secret(
            method.encrypted_secret,
            method.user_id,
            method.id,
            settings,
        )
    except InvalidMfaSecretError as error:
        await session.rollback()
        raise MfaConfigurationError from error

    recovery_used = False
    counter = matching_totp_counter(
        secret,
        code,
        now=authenticated_at,
        last_used_counter=method.last_used_counter,
    )
    if counter is not None:
        method.last_used_counter = counter
    else:
        recovery = await session.scalar(
            select(MfaRecoveryCode)
            .where(
                MfaRecoveryCode.mfa_method_id == method.id,
                MfaRecoveryCode.code_digest == digest_recovery_code(code, settings),
                MfaRecoveryCode.used_at.is_(None),
            )
            .with_for_update()
        )
        if recovery is None:
            await session.rollback()
            raise InvalidMfaCodeError
        recovery.used_at = authenticated_at
        recovery_used = True

    token.consumed_at = authenticated_at
    append_audit_event(
        session,
        AuditEventType.OWNER_MFA_AUTHENTICATED,
        occurred_at=authenticated_at,
        actor_user_id=token.user_id,
        target_user_id=token.user_id,
        request_id=request_id,
        details={"recovery_code": recovery_used},
    )
    return await issue_session_for_user(
        session,
        settings,
        user=token.user,
        authenticated_at=authenticated_at,
        mfa_authenticated_at=authenticated_at,
        user_agent=user_agent,
        request_id=request_id,
    )


async def reset_owner_mfa(
    session: AsyncSession,
    settings: Settings,
    *,
    email: str,
    password: str,
    now: datetime | None = None,
) -> None:
    """Deployment-only recovery that removes MFA and revokes every owner session."""
    reset_at = _utc_now(now)
    owner = await session.scalar(
        select(User).where(User.email == normalize_email(email)).with_for_update()
    )
    if owner is None:
        await session.rollback()
        raise OwnerAccessDeniedError
    _assert_primary_owner(owner)
    if not await _password_matches(password, owner.password_hash):
        await session.rollback()
        raise InvalidOwnerPasswordError
    await session.execute(delete(MfaMethod).where(MfaMethod.user_id == owner.id))
    await session.execute(
        update(OneTimeToken)
        .where(
            OneTimeToken.user_id == owner.id,
            OneTimeToken.purpose == OneTimeTokenPurpose.MFA_LOGIN,
            OneTimeToken.consumed_at.is_(None),
        )
        .values(consumed_at=reset_at)
    )
    await session.execute(
        update(RefreshSession)
        .where(RefreshSession.user_id == owner.id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=reset_at)
    )
    append_audit_event(
        session,
        AuditEventType.OWNER_MFA_RESET,
        occurred_at=reset_at,
        actor_user_id=owner.id,
        target_user_id=owner.id,
        details={"sessions_revoked": True},
    )
    await session.commit()
