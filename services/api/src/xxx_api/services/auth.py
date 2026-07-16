"""Transactional authentication application service.

HTTP routes and email delivery are intentionally separate adapters. Raw one-time
and session tokens leave this module only in explicit result objects and must
never be logged or persisted in plaintext.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from anyio import to_thread
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from xxx_api.config import Settings
from xxx_api.domain.auth import OneTimeTokenPurpose, UserStatus
from xxx_api.domain.roles import Role
from xxx_api.models.identity import OneTimeToken, RefreshSession, User
from xxx_api.security.email import normalize_email
from xxx_api.security.passwords import MAX_PASSWORD_BYTES, hash_password, verify_password
from xxx_api.security.tokens import (
    AccessTokenClaims,
    decode_access_token,
    digest_opaque_token,
    issue_access_token,
    issue_csrf_token,
    issue_opaque_token,
    verify_csrf_token,
)

DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$mkM1dnEgmRyOd7Ln+ojEqg$"
    "7OlgYON6EjiNGXmLbr4sZlwqgKLQfht1DLAqq5vI6ww"
)


class AuthenticationError(Exception):
    """Base error safe for route adapters to translate generically."""


class InvalidCredentialsError(AuthenticationError):
    """Credentials or bearer state did not authenticate."""


class VerificationRequiredError(AuthenticationError):
    """Correct buyer credentials require email verification before login."""


class InvalidOneTimeTokenError(AuthenticationError):
    """A verification or reset token is invalid, expired, or consumed."""


class InvalidSessionError(AuthenticationError):
    """A refresh or access session is invalid, expired, or revoked."""


class RefreshTokenReuseError(InvalidSessionError):
    """A rotated refresh token was replayed and its family was revoked."""


class InvalidCsrfTokenError(AuthenticationError):
    """Cookie-authenticated state change lacked its session-bound CSRF proof."""


@dataclass(frozen=True, slots=True)
class RegistrationIssue:
    """New buyer identity plus the verification token for the email adapter."""

    user_id: UUID
    verification_token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PasswordResetIssue:
    """Password-reset token for the email adapter."""

    user_id: UUID
    reset_token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class SessionIssue:
    """Bearer values returned once to the HTTP cookie adapter."""

    user_id: UUID
    email: str
    display_name: str
    role: Role
    access_token: str
    refresh_token: str
    csrf_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


def _utc_now(now: datetime | None) -> datetime:
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _stored_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _validate_display_name(display_name: str) -> str:
    normalized = " ".join(display_name.split())
    if not normalized or len(normalized) > 100:
        raise ValueError("display name must contain between 1 and 100 characters")
    return normalized


def _user_agent_digest(user_agent: str | None) -> str | None:
    if not user_agent:
        return None
    bounded = user_agent[:2048].encode("utf-8")
    return sha256(bounded).hexdigest()


async def _verify_password(password: str, encoded_hash: str) -> bool:
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return False
    return await to_thread.run_sync(verify_password, password, encoded_hash)


async def register_buyer(
    session: AsyncSession,
    settings: Settings,
    *,
    email: str,
    display_name: str,
    password: str,
    now: datetime | None = None,
) -> RegistrationIssue | None:
    """Create one pending buyer; return none for an existing normalized email."""
    normalized_email = normalize_email(email)
    normalized_name = _validate_display_name(display_name)
    password_hash = await to_thread.run_sync(hash_password, password)
    issued_at = _utc_now(now)
    opaque_token = issue_opaque_token(settings)
    expires_at = issued_at + timedelta(hours=settings.email_verification_ttl_hours)

    existing_id = await session.scalar(select(User.id).where(User.email == normalized_email))
    if existing_id is not None:
        await session.rollback()
        return None

    user = User(
        email=normalized_email,
        display_name=normalized_name,
        password_hash=password_hash,
        role=Role.BUYER,
        status=UserStatus.PENDING_VERIFICATION,
        password_changed_at=issued_at,
    )
    session.add(user)
    try:
        await session.flush()
        session.add(
            OneTimeToken(
                user_id=user.id,
                purpose=OneTimeTokenPurpose.VERIFY_EMAIL,
                token_digest=opaque_token.digest,
                expires_at=expires_at,
            )
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return None

    return RegistrationIssue(
        user_id=user.id,
        verification_token=opaque_token.raw,
        expires_at=expires_at,
    )


async def issue_email_verification(
    session: AsyncSession,
    settings: Settings,
    *,
    email: str,
    now: datetime | None = None,
) -> RegistrationIssue | None:
    """Issue a replacement verification token only for a pending buyer."""
    normalized_email = normalize_email(email)
    user = await session.scalar(
        select(User).where(User.email == normalized_email).with_for_update()
    )
    if user is None or user.status is not UserStatus.PENDING_VERIFICATION:
        await session.rollback()
        return None

    issued_at = _utc_now(now)
    opaque_token = issue_opaque_token(settings)
    expires_at = issued_at + timedelta(hours=settings.email_verification_ttl_hours)
    await session.execute(
        update(OneTimeToken)
        .where(
            OneTimeToken.user_id == user.id,
            OneTimeToken.purpose == OneTimeTokenPurpose.VERIFY_EMAIL,
            OneTimeToken.consumed_at.is_(None),
        )
        .values(consumed_at=issued_at)
    )
    session.add(
        OneTimeToken(
            user_id=user.id,
            purpose=OneTimeTokenPurpose.VERIFY_EMAIL,
            token_digest=opaque_token.digest,
            expires_at=expires_at,
        )
    )
    await session.commit()
    return RegistrationIssue(
        user_id=user.id,
        verification_token=opaque_token.raw,
        expires_at=expires_at,
    )


async def verify_email(
    session: AsyncSession,
    settings: Settings,
    *,
    raw_token: str,
    now: datetime | None = None,
) -> UUID:
    """Consume one verification token and activate its buyer identity."""
    verified_at = _utc_now(now)
    token_digest = digest_opaque_token(raw_token, settings)
    token_record = await session.scalar(
        select(OneTimeToken)
        .where(
            OneTimeToken.token_digest == token_digest,
            OneTimeToken.purpose == OneTimeTokenPurpose.VERIFY_EMAIL,
        )
        .options(selectinload(OneTimeToken.user))
        .with_for_update()
    )
    if (
        token_record is None
        or token_record.consumed_at is not None
        or _stored_utc(token_record.expires_at) <= verified_at
        or token_record.user.status is UserStatus.DISABLED
    ):
        await session.rollback()
        raise InvalidOneTimeTokenError

    token_record.user.email_verified_at = verified_at
    token_record.user.status = UserStatus.ACTIVE
    await session.execute(
        update(OneTimeToken)
        .where(
            OneTimeToken.user_id == token_record.user_id,
            OneTimeToken.purpose == OneTimeTokenPurpose.VERIFY_EMAIL,
            OneTimeToken.consumed_at.is_(None),
        )
        .values(consumed_at=verified_at)
    )
    await session.commit()
    return token_record.user_id


def _build_session_issue(
    *,
    user: User,
    session_id: UUID,
    refresh_token: str,
    refresh_expires_at: datetime,
    issued_at: datetime,
    settings: Settings,
) -> SessionIssue:
    return SessionIssue(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        access_token=issue_access_token(
            user_id=user.id,
            session_id=session_id,
            role=user.role,
            settings=settings,
            now=issued_at,
        ),
        refresh_token=refresh_token,
        csrf_token=issue_csrf_token(session_id, settings),
        access_expires_at=issued_at
        + timedelta(seconds=settings.access_token_ttl_seconds),
        refresh_expires_at=refresh_expires_at,
    )


async def login(
    session: AsyncSession,
    settings: Settings,
    *,
    email: str,
    password: str,
    user_agent: str | None = None,
    now: datetime | None = None,
) -> SessionIssue:
    """Authenticate an active verified buyer or provisioned owner."""
    normalized_email = normalize_email(email)
    user = await session.scalar(
        select(User).where(User.email == normalized_email).with_for_update()
    )
    password_matches = await _verify_password(
        password,
        user.password_hash if user is not None else DUMMY_PASSWORD_HASH,
    )
    if user is None or not password_matches or user.status is UserStatus.DISABLED:
        await session.rollback()
        raise InvalidCredentialsError
    if user.status is not UserStatus.ACTIVE or user.email_verified_at is None:
        await session.rollback()
        raise VerificationRequiredError

    issued_at = _utc_now(now)
    active_family_ids = (
        await session.scalars(
            select(RefreshSession.family_id)
            .where(
                RefreshSession.user_id == user.id,
                RefreshSession.rotated_at.is_(None),
                RefreshSession.revoked_at.is_(None),
                RefreshSession.expires_at > issued_at,
            )
            .order_by(RefreshSession.created_at)
        )
    ).all()
    families_to_revoke = 1 + len(active_family_ids) - settings.max_active_sessions_per_user
    for family_id in active_family_ids[: max(0, families_to_revoke)]:
        await _revoke_family(session, family_id, issued_at)

    opaque_token = issue_opaque_token(settings)
    refresh_expires_at = issued_at + timedelta(days=settings.refresh_token_ttl_days)
    refresh_session = RefreshSession(
        user_id=user.id,
        token_digest=opaque_token.digest,
        expires_at=refresh_expires_at,
        created_at=issued_at,
        user_agent_digest=_user_agent_digest(user_agent),
    )
    session.add(refresh_session)
    await session.commit()
    return _build_session_issue(
        user=user,
        session_id=refresh_session.id,
        refresh_token=opaque_token.raw,
        refresh_expires_at=refresh_expires_at,
        issued_at=issued_at,
        settings=settings,
    )


async def _revoke_family(
    session: AsyncSession,
    family_id: UUID,
    revoked_at: datetime,
) -> None:
    await session.execute(
        update(RefreshSession)
        .where(
            RefreshSession.family_id == family_id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=revoked_at)
    )


async def rotate_refresh_token(
    session: AsyncSession,
    settings: Settings,
    *,
    raw_token: str,
    csrf_cookie: str,
    csrf_header: str,
    user_agent: str | None = None,
    now: datetime | None = None,
) -> SessionIssue:
    """Rotate one refresh token and revoke its family when replay is detected."""
    rotated_at = _utc_now(now)
    token_digest = digest_opaque_token(raw_token, settings)
    current = await session.scalar(
        select(RefreshSession)
        .where(RefreshSession.token_digest == token_digest)
        .options(selectinload(RefreshSession.user))
        .with_for_update()
    )
    if current is None:
        await session.rollback()
        raise InvalidSessionError
    if not verify_csrf_token(
        csrf_cookie,
        csrf_header,
        current.id,
        settings,
    ):
        await session.rollback()
        raise InvalidCsrfTokenError
    if current.rotated_at is not None:
        await _revoke_family(session, current.family_id, rotated_at)
        await session.commit()
        raise RefreshTokenReuseError
    if current.revoked_at is not None or _stored_utc(current.expires_at) <= rotated_at:
        if current.revoked_at is None:
            current.revoked_at = rotated_at
            await session.commit()
        else:
            await session.rollback()
        raise InvalidSessionError
    if current.user.status is not UserStatus.ACTIVE:
        await _revoke_family(session, current.family_id, rotated_at)
        await session.commit()
        raise InvalidSessionError

    opaque_token = issue_opaque_token(settings)
    refresh_expires_at = _stored_utc(current.expires_at)
    replacement = RefreshSession(
        user_id=current.user_id,
        family_id=current.family_id,
        token_digest=opaque_token.digest,
        expires_at=refresh_expires_at,
        created_at=rotated_at,
        user_agent_digest=_user_agent_digest(user_agent),
    )
    session.add(replacement)
    await session.flush()
    current.rotated_at = rotated_at
    current.replaced_by_id = replacement.id
    await session.commit()
    return _build_session_issue(
        user=current.user,
        session_id=replacement.id,
        refresh_token=opaque_token.raw,
        refresh_expires_at=refresh_expires_at,
        issued_at=rotated_at,
        settings=settings,
    )


async def logout(
    session: AsyncSession,
    settings: Settings,
    *,
    raw_refresh_token: str,
    csrf_cookie: str,
    csrf_header: str,
    now: datetime | None = None,
) -> None:
    """Idempotently revoke the complete family for the supplied refresh token."""
    revoked_at = _utc_now(now)
    token_digest = digest_opaque_token(raw_refresh_token, settings)
    current = await session.scalar(
        select(RefreshSession).where(RefreshSession.token_digest == token_digest)
    )
    if current is not None:
        if not verify_csrf_token(
            csrf_cookie,
            csrf_header,
            current.id,
            settings,
        ):
            await session.rollback()
            raise InvalidCsrfTokenError
        await _revoke_family(session, current.family_id, revoked_at)
        await session.commit()
    else:
        await session.rollback()


async def authenticate_access_token(
    session: AsyncSession,
    settings: Settings,
    *,
    raw_token: str,
    now: datetime | None = None,
) -> User:
    """Validate JWT claims against current user and server-side session state."""
    try:
        claims: AccessTokenClaims = decode_access_token(raw_token, settings)
    except ValueError as error:
        raise InvalidSessionError from error

    current = await session.scalar(
        select(RefreshSession)
        .where(RefreshSession.id == claims.session_id)
        .options(selectinload(RefreshSession.user))
    )
    if current is None:
        raise InvalidSessionError
    user = current.user
    password_changed_at = _stored_utc(user.password_changed_at)
    checked_at = _utc_now(now)
    if (
        current.user_id != claims.user_id
        or current.revoked_at is not None
        or current.rotated_at is not None
        or _stored_utc(current.expires_at) <= checked_at
        or user.status is not UserStatus.ACTIVE
        or user.role is not claims.role
        or int(claims.issued_at.timestamp()) < int(password_changed_at.timestamp())
    ):
        raise InvalidSessionError
    return user


async def request_password_reset(
    session: AsyncSession,
    settings: Settings,
    *,
    email: str,
    now: datetime | None = None,
) -> PasswordResetIssue | None:
    """Issue a reset token only for an active verified account."""
    normalized_email = normalize_email(email)
    user = await session.scalar(
        select(User).where(User.email == normalized_email).with_for_update()
    )
    if (
        user is None
        or user.status is not UserStatus.ACTIVE
        or user.email_verified_at is None
    ):
        await session.rollback()
        return None

    issued_at = _utc_now(now)
    opaque_token = issue_opaque_token(settings)
    expires_at = issued_at + timedelta(minutes=settings.password_reset_ttl_minutes)
    await session.execute(
        update(OneTimeToken)
        .where(
            OneTimeToken.user_id == user.id,
            OneTimeToken.purpose == OneTimeTokenPurpose.RESET_PASSWORD,
            OneTimeToken.consumed_at.is_(None),
        )
        .values(consumed_at=issued_at)
    )
    session.add(
        OneTimeToken(
            user_id=user.id,
            purpose=OneTimeTokenPurpose.RESET_PASSWORD,
            token_digest=opaque_token.digest,
            expires_at=expires_at,
        )
    )
    await session.commit()
    return PasswordResetIssue(
        user_id=user.id,
        reset_token=opaque_token.raw,
        expires_at=expires_at,
    )


async def reset_password(
    session: AsyncSession,
    settings: Settings,
    *,
    raw_token: str,
    new_password: str,
    now: datetime | None = None,
) -> UUID:
    """Consume a reset token, replace the password, and revoke every session."""
    password_hash = await to_thread.run_sync(hash_password, new_password)
    changed_at = _utc_now(now)
    token_digest = digest_opaque_token(raw_token, settings)
    token_record = await session.scalar(
        select(OneTimeToken)
        .where(
            OneTimeToken.token_digest == token_digest,
            OneTimeToken.purpose == OneTimeTokenPurpose.RESET_PASSWORD,
        )
        .options(selectinload(OneTimeToken.user))
        .with_for_update()
    )
    if (
        token_record is None
        or token_record.consumed_at is not None
        or _stored_utc(token_record.expires_at) <= changed_at
        or token_record.user.status is not UserStatus.ACTIVE
    ):
        await session.rollback()
        raise InvalidOneTimeTokenError

    token_record.user.password_hash = password_hash
    token_record.user.password_changed_at = changed_at
    await session.execute(
        update(OneTimeToken)
        .where(
            OneTimeToken.user_id == token_record.user_id,
            OneTimeToken.purpose == OneTimeTokenPurpose.RESET_PASSWORD,
            OneTimeToken.consumed_at.is_(None),
        )
        .values(consumed_at=changed_at)
    )
    await session.execute(
        update(RefreshSession)
        .where(
            RefreshSession.user_id == token_record.user_id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=changed_at)
    )
    await session.commit()
    return token_record.user_id
