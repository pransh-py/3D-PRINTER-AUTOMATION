"""Singleton owner, MFA enrollment/login/recovery, and audit integration tests."""

from asyncio import run
from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from xxx_api.config import Settings
from xxx_api.domain.auth import AuditEventType
from xxx_api.models import AuditEvent, Base, MfaMethod, MfaRecoveryCode, RefreshSession, User
from xxx_api.services.auth import (
    MfaChallengeIssue,
    SessionIssue,
    authenticate_access_principal,
    login,
)
from xxx_api.services.owner_security import (
    InvalidMfaCodeError,
    InvalidOwnerPasswordError,
    OwnerAccessDeniedError,
    OwnerAlreadyProvisionedError,
    complete_owner_mfa_login,
    confirm_owner_mfa_enrollment,
    provision_owner,
    reset_owner_mfa,
    start_owner_mfa_enrollment,
)


async def _database() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def test_singleton_owner_enrolls_and_completes_replay_safe_mfa_login() -> None:
    async def scenario() -> None:
        engine, sessions = await _database()
        settings = Settings(environment="test")
        started_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=5)
        password = "correct horse battery staple"

        async with sessions() as session:
            owner_id = await provision_owner(
                session,
                settings,
                email=" Owner@Example.com ",
                display_name=" Primary   Owner ",
                password=password,
                now=started_at,
            )
        async with sessions() as session:
            with pytest.raises(OwnerAlreadyProvisionedError):
                await provision_owner(
                    session,
                    settings,
                    email="second@example.com",
                    display_name="Second Owner",
                    password=password,
                    now=started_at,
                )
        async with sessions() as session:
            password_session = await login(
                session,
                settings,
                email="owner@example.com",
                password=password,
                now=started_at + timedelta(seconds=1),
            )
            assert isinstance(password_session, SessionIssue)
        async with sessions() as session:
            principal = await authenticate_access_principal(
                session,
                settings,
                raw_token=password_session.access_token,
                now=started_at + timedelta(seconds=2),
            )
            with pytest.raises(InvalidOwnerPasswordError):
                await start_owner_mfa_enrollment(
                    session,
                    settings,
                    principal=principal,
                    current_password="wrong password",
                    now=started_at + timedelta(seconds=2),
                )
        async with sessions() as session:
            principal = await authenticate_access_principal(
                session,
                settings,
                raw_token=password_session.access_token,
                now=started_at + timedelta(seconds=3),
            )
            enrollment = await start_owner_mfa_enrollment(
                session,
                settings,
                principal=principal,
                current_password=password,
                now=started_at + timedelta(seconds=3),
            )
            assert enrollment.provisioning_uri.startswith("otpauth://totp/")
        async with sessions() as session:
            method = await session.scalar(select(MfaMethod).where(MfaMethod.user_id == owner_id))
            assert method is not None
            assert enrollment.secret not in method.encrypted_secret
        confirmation_at = started_at + timedelta(seconds=30)
        confirmation_code = pyotp.TOTP(enrollment.secret).at(int(confirmation_at.timestamp()))
        async with sessions() as session:
            principal = await authenticate_access_principal(
                session,
                settings,
                raw_token=password_session.access_token,
                now=confirmation_at,
            )
            confirmation = await confirm_owner_mfa_enrollment(
                session,
                settings,
                principal=principal,
                code=confirmation_code,
                now=confirmation_at,
            )
            assert len(confirmation.recovery_codes) == 10
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(MfaRecoveryCode)) == 10
            owner_login = await login(
                session,
                settings,
                email="owner@example.com",
                password=password,
                now=started_at + timedelta(seconds=60),
            )
            assert isinstance(owner_login, MfaChallengeIssue)
        mfa_login_at = started_at + timedelta(seconds=60)
        mfa_code = pyotp.TOTP(enrollment.secret).at(int(mfa_login_at.timestamp()))
        async with sessions() as session:
            authenticated = await complete_owner_mfa_login(
                session,
                settings,
                challenge=owner_login.challenge,
                code=mfa_code,
                now=mfa_login_at,
            )
            assert authenticated.role.value == "owner"
        async with sessions() as session:
            with pytest.raises(InvalidMfaCodeError):
                await complete_owner_mfa_login(
                    session,
                    settings,
                    challenge=owner_login.challenge,
                    code=mfa_code,
                    now=mfa_login_at,
                )
            audit_types = set(await session.scalars(select(AuditEvent.event_type)))
            assert AuditEventType.OWNER_PROVISIONED in audit_types
            assert AuditEventType.OWNER_MFA_ENABLED in audit_types
            assert AuditEventType.OWNER_MFA_AUTHENTICATED in audit_types
            created_session_event = await session.scalar(
                select(AuditEvent).where(
                    AuditEvent.event_type == AuditEventType.SESSION_CREATED,
                )
            )
            assert created_session_event is not None
            assert created_session_event.session_id is not None
            first_audit = await session.scalar(select(AuditEvent))
            assert first_audit is not None
            first_audit.request_id = "mutated"
            with pytest.raises(RuntimeError, match="append-only"):
                await session.flush()
            await session.rollback()
        await engine.dispose()

    run(scenario())


def test_recovery_code_is_one_time_and_cli_reset_revokes_owner_sessions() -> None:
    async def scenario() -> None:
        engine, sessions = await _database()
        settings = Settings(environment="test")
        started_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=5)
        password = "correct horse battery staple"
        async with sessions() as session:
            await provision_owner(
                session,
                settings,
                email="owner@example.com",
                display_name="Owner",
                password=password,
                now=started_at,
            )
        async with sessions() as session:
            first_session = await login(
                session,
                settings,
                email="owner@example.com",
                password=password,
                now=started_at + timedelta(seconds=1),
            )
            assert isinstance(first_session, SessionIssue)
        async with sessions() as session:
            principal = await authenticate_access_principal(
                session,
                settings,
                raw_token=first_session.access_token,
                now=started_at + timedelta(seconds=2),
            )
            enrollment = await start_owner_mfa_enrollment(
                session,
                settings,
                principal=principal,
                current_password=password,
                now=started_at + timedelta(seconds=2),
            )
        confirmed_at = started_at + timedelta(seconds=30)
        async with sessions() as session:
            principal = await authenticate_access_principal(
                session,
                settings,
                raw_token=first_session.access_token,
                now=confirmed_at,
            )
            confirmation = await confirm_owner_mfa_enrollment(
                session,
                settings,
                principal=principal,
                code=pyotp.TOTP(enrollment.secret).at(int(confirmed_at.timestamp())),
                now=confirmed_at,
            )
        recovery_code = confirmation.recovery_codes[0]
        async with sessions() as session:
            challenge = await login(
                session,
                settings,
                email="owner@example.com",
                password=password,
                now=started_at + timedelta(seconds=60),
            )
            assert isinstance(challenge, MfaChallengeIssue)
        async with sessions() as session:
            recovered_session = await complete_owner_mfa_login(
                session,
                settings,
                challenge=challenge.challenge,
                code=recovery_code,
                now=started_at + timedelta(seconds=60),
            )
        async with sessions() as session:
            second_challenge = await login(
                session,
                settings,
                email="owner@example.com",
                password=password,
                now=started_at + timedelta(seconds=90),
            )
            assert isinstance(second_challenge, MfaChallengeIssue)
        async with sessions() as session:
            with pytest.raises(InvalidMfaCodeError):
                await complete_owner_mfa_login(
                    session,
                    settings,
                    challenge=second_challenge.challenge,
                    code=recovery_code,
                    now=started_at + timedelta(seconds=90),
                )
        async with sessions() as session:
            with pytest.raises(InvalidOwnerPasswordError):
                await reset_owner_mfa(
                    session,
                    settings,
                    email="owner@example.com",
                    password="wrong password",
                    now=started_at + timedelta(seconds=100),
                )
        async with sessions() as session:
            await reset_owner_mfa(
                session,
                settings,
                email="owner@example.com",
                password=password,
                now=started_at + timedelta(seconds=101),
            )
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(MfaMethod)) == 0
            active_sessions = await session.scalar(
                select(func.count())
                .select_from(RefreshSession)
                .where(RefreshSession.revoked_at.is_(None))
            )
            assert active_sessions == 0
            assert recovered_session.access_token
        await engine.dispose()

    run(scenario())


def test_buyer_cannot_enter_owner_enrollment_service() -> None:
    async def scenario() -> None:
        engine, sessions = await _database()
        settings = Settings(environment="test")
        now = datetime.now(UTC).replace(microsecond=0)
        async with sessions() as session:
            buyer = User(
                email="buyer@example.com",
                display_name="Buyer",
                password_hash="unused",
                status="active",
                email_verified_at=now,
                password_changed_at=now,
            )
            session.add(buyer)
            await session.flush()
            refresh = RefreshSession(
                user_id=buyer.id,
                token_digest="a" * 64,
                expires_at=now + timedelta(days=1),
                authenticated_at=now,
            )
            session.add(refresh)
            await session.commit()
            from xxx_api.services.auth import AuthenticatedPrincipal

            principal = AuthenticatedPrincipal(user=buyer, refresh_session=refresh)
            with pytest.raises(OwnerAccessDeniedError):
                await start_owner_mfa_enrollment(
                    session,
                    settings,
                    principal=principal,
                    current_password="irrelevant",
                    now=now,
                )
        await engine.dispose()

    run(scenario())
