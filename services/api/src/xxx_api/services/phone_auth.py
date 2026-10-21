"""Phone proofs are single-use, bounded and never imply email ownership or owner access."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from secrets import randbelow
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from xxx_api.config import Settings
from xxx_api.domain.auth import AuditEventType, UserStatus
from xxx_api.domain.roles import Role
from xxx_api.models.identity import PhoneOtpChallenge, User
from xxx_api.phone_otp import PhoneOtpDeliveryError, PhoneOtpSender
from xxx_api.security.tokens import digest_opaque_token, issue_opaque_token
from xxx_api.services.audit import append_audit_event
from xxx_api.services.auth import SessionIssue, issue_session_for_user

TTL_SECONDS = 300
COOLDOWN_SECONDS = 60


class InvalidPhoneCodeError(Exception):
    pass


class PhoneAccountNotFoundError(Exception):
    pass


class PhoneVerificationConflictError(Exception):
    pass


class PhoneOtpCooldownError(Exception):
    def __init__(self, retry_after: int = COOLDOWN_SECONDS) -> None:
        self.retry_after = max(1, retry_after)


@dataclass(frozen=True)
class PhoneChallengeIssue:
    challenge: str
    expires_in_seconds: int = TTL_SECONDS
    resend_after_seconds: int = COOLDOWN_SECONDS


def utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(UTC)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def issue_phone_challenge(
    session: AsyncSession,
    settings: Settings,
    sender: PhoneOtpSender,
    *,
    phone: str,
    purpose: str,
    display_name: str | None,
    now: datetime | None = None,
) -> PhoneChallengeIssue:
    current = utc(now)
    cutoff = current - timedelta(seconds=COOLDOWN_SECONDS)
    recent = await session.scalar(
        select(PhoneOtpChallenge)
        .where(
            PhoneOtpChallenge.phone_e164 == phone,
            or_(
                PhoneOtpChallenge.delivered_at > cutoff,
                and_(
                    PhoneOtpChallenge.consumed_at.is_(None), PhoneOtpChallenge.created_at > cutoff
                ),
            ),
        )
        .order_by(PhoneOtpChallenge.created_at.desc())
        .limit(1)
    )
    if recent:
        sent_at = recent.delivered_at or recent.created_at
        raise PhoneOtpCooldownError(
            COOLDOWN_SECONDS - int((current - utc(sent_at)).total_seconds())
        )
    await session.execute(
        update(PhoneOtpChallenge)
        .where(
            PhoneOtpChallenge.phone_e164 == phone,
            PhoneOtpChallenge.consumed_at.is_(None),
            PhoneOtpChallenge.created_at <= cutoff,
            or_(PhoneOtpChallenge.delivered_at.is_(None), PhoneOtpChallenge.delivered_at <= cutoff),
        )
        .values(consumed_at=current)
    )
    handle = issue_opaque_token(settings)
    identifier = uuid4()
    code = f"{randbelow(1_000_000):06d}"
    row = PhoneOtpChallenge(
        id=identifier,
        challenge_digest=handle.digest,
        purpose=purpose,
        phone_e164=phone,
        display_name=" ".join(display_name.split()) if display_name else None,
        code_digest=digest_opaque_token(f"phone-otp:{identifier}:{code}", settings),
        attempt_count=0,
        created_at=current,
        expires_at=current + timedelta(seconds=TTL_SECONDS),
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise PhoneOtpCooldownError from None
    # The bounded adapter timeout (<=30s) must remain below the 60s pending-send window.
    try:
        await sender.send_code(phone, code)
    except PhoneOtpDeliveryError:
        await session.execute(
            update(PhoneOtpChallenge)
            .where(PhoneOtpChallenge.id == identifier, PhoneOtpChallenge.consumed_at.is_(None))
            .values(consumed_at=utc(now))
        )
        await session.commit()
        raise
    changed = await session.scalar(
        update(PhoneOtpChallenge)
        .where(PhoneOtpChallenge.id == identifier, PhoneOtpChallenge.consumed_at.is_(None))
        .values(delivered_at=current)
        .returning(PhoneOtpChallenge.id)
    )
    await session.commit()
    if changed is None:
        raise PhoneOtpDeliveryError("ack_lost")
    return PhoneChallengeIssue(handle.raw)


async def verify_phone_challenge(
    session: AsyncSession,
    settings: Settings,
    *,
    raw_challenge: str,
    code: str,
    user_agent: str | None = None,
    request_id: str | None = None,
    now: datetime | None = None,
) -> SessionIssue:
    current = utc(now)
    reserved = (
        await session.execute(
            update(PhoneOtpChallenge)
            .where(
                PhoneOtpChallenge.challenge_digest == digest_opaque_token(raw_challenge, settings),
                PhoneOtpChallenge.consumed_at.is_(None),
                PhoneOtpChallenge.delivered_at.is_not(None),
                PhoneOtpChallenge.expires_at > current,
                PhoneOtpChallenge.attempt_count < 5,
            )
            .values(attempt_count=PhoneOtpChallenge.attempt_count + 1)
            .returning(
                PhoneOtpChallenge.id,
                PhoneOtpChallenge.phone_e164,
                PhoneOtpChallenge.purpose,
                PhoneOtpChallenge.display_name,
                PhoneOtpChallenge.code_digest,
                PhoneOtpChallenge.attempt_count,
            )
        )
    ).first()
    await session.commit()
    if reserved is None:
        raise InvalidPhoneCodeError
    identifier, phone, purpose, name, digest, attempt = reserved
    if not compare_digest(digest_opaque_token(f"phone-otp:{identifier}:{code}", settings), digest):
        if attempt >= 5:
            await session.execute(
                update(PhoneOtpChallenge)
                .where(PhoneOtpChallenge.id == identifier, PhoneOtpChallenge.consumed_at.is_(None))
                .values(consumed_at=current)
            )
            await session.commit()
        raise InvalidPhoneCodeError
    consumed = await session.scalar(
        update(PhoneOtpChallenge)
        .where(PhoneOtpChallenge.id == identifier, PhoneOtpChallenge.consumed_at.is_(None))
        .values(consumed_at=current)
        .returning(PhoneOtpChallenge.id)
    )
    if consumed is None:
        await session.rollback()
        raise InvalidPhoneCodeError
    user = await session.scalar(select(User).where(User.phone_e164 == phone).with_for_update())
    if user is not None and (user.role is not Role.BUYER or user.status is not UserStatus.ACTIVE):
        await session.commit()
        raise InvalidPhoneCodeError
    if user is None and purpose != "signup":
        await session.commit()
        raise PhoneAccountNotFoundError
    if user is None:
        user = User(
            email=None,
            password_hash=None,
            display_name=name,
            role=Role.BUYER,
            status=UserStatus.ACTIVE,
            phone_e164=phone,
            phone_verified_at=current,
            password_changed_at=current,
        )
        session.add(user)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            raise PhoneVerificationConflictError from None
        append_audit_event(
            session,
            AuditEventType.BUYER_REGISTERED,
            occurred_at=current,
            actor_user_id=user.id,
            target_user_id=user.id,
            request_id=request_id,
            details={"role": "buyer", "method": "phone_otp"},
        )
    return await issue_session_for_user(
        session,
        settings,
        user=user,
        authenticated_at=current,
        mfa_authenticated_at=None,
        user_agent=user_agent,
        request_id=request_id,
    )
