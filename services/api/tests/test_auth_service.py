"""Transactional authentication-service integration tests."""

from asyncio import run
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from xxx_api.config import Settings
from xxx_api.domain.auth import UserStatus
from xxx_api.models import Base, RefreshSession, User
from xxx_api.services.auth import (
    InvalidCredentialsError,
    InvalidOneTimeTokenError,
    InvalidSessionError,
    RefreshTokenReuseError,
    VerificationRequiredError,
    authenticate_access_token,
    login,
    logout,
    register_buyer,
    request_password_reset,
    reset_password,
    rotate_refresh_token,
    verify_email,
)


async def _database() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def test_registration_is_normalized_generic_and_verifiable() -> None:
    async def scenario() -> None:
        engine, sessions = await _database()
        settings = Settings(environment="test")
        now = datetime.now(UTC)
        async with sessions() as session:
            registration = await register_buyer(
                session,
                settings,
                email="  Buyer@Example.COM ",
                display_name="  First   Buyer  ",
                password="correct horse battery staple",
                now=now,
            )
            assert registration is not None

        async with sessions() as session:
            duplicate = await register_buyer(
                session,
                settings,
                email="buyer@example.com",
                display_name="Different Name",
                password="another valid buyer password",
                now=now,
            )
            assert duplicate is None
            assert await session.scalar(select(func.count()).select_from(User)) == 1
            buyer = await session.scalar(select(User))
            assert buyer is not None
            assert buyer.email == "buyer@example.com"
            assert buyer.display_name == "First Buyer"
            assert buyer.status is UserStatus.PENDING_VERIFICATION
            assert buyer.password_hash != "correct horse battery staple"

        async with sessions() as session:
            with pytest.raises(VerificationRequiredError):
                await login(
                    session,
                    settings,
                    email="buyer@example.com",
                    password="correct horse battery staple",
                    now=now,
                )

        async with sessions() as session:
            user_id = await verify_email(
                session,
                settings,
                raw_token=registration.verification_token,
                now=now + timedelta(minutes=1),
            )
            assert user_id == registration.user_id

        async with sessions() as session:
            with pytest.raises(InvalidOneTimeTokenError):
                await verify_email(
                    session,
                    settings,
                    raw_token=registration.verification_token,
                    now=now + timedelta(minutes=2),
                )
        await engine.dispose()

    run(scenario())


def test_refresh_rotation_replay_revokes_the_complete_family() -> None:
    async def scenario() -> None:
        engine, sessions = await _database()
        settings = Settings(environment="test")
        now = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)

        async with sessions() as session:
            registration = await register_buyer(
                session,
                settings,
                email="buyer@example.com",
                display_name="Buyer",
                password="correct horse battery staple",
                now=now,
            )
            assert registration is not None
        async with sessions() as session:
            await verify_email(
                session,
                settings,
                raw_token=registration.verification_token,
                now=now + timedelta(seconds=1),
            )
        async with sessions() as session:
            original = await login(
                session,
                settings,
                email="buyer@example.com",
                password="correct horse battery staple",
                user_agent="test-browser/1",
                now=now + timedelta(seconds=2),
            )
        async with sessions() as session:
            principal = await authenticate_access_token(
                session,
                settings,
                raw_token=original.access_token,
                now=now + timedelta(seconds=3),
            )
            assert principal.id == registration.user_id

        async with sessions() as session:
            replacement = await rotate_refresh_token(
                session,
                settings,
                raw_token=original.refresh_token,
                user_agent="test-browser/1",
                now=now + timedelta(seconds=4),
            )
            assert replacement.refresh_expires_at == original.refresh_expires_at
        async with sessions() as session:
            with pytest.raises(InvalidSessionError):
                await authenticate_access_token(
                    session,
                    settings,
                    raw_token=original.access_token,
                    now=now + timedelta(seconds=5),
                )
            principal = await authenticate_access_token(
                session,
                settings,
                raw_token=replacement.access_token,
                now=now + timedelta(seconds=5),
            )
            assert principal.id == registration.user_id

        async with sessions() as session:
            with pytest.raises(RefreshTokenReuseError):
                await rotate_refresh_token(
                    session,
                    settings,
                    raw_token=original.refresh_token,
                    now=now + timedelta(seconds=6),
                )
        async with sessions() as session:
            with pytest.raises(InvalidSessionError):
                await authenticate_access_token(
                    session,
                    settings,
                    raw_token=replacement.access_token,
                    now=now + timedelta(seconds=7),
                )
            family_rows = (
                await session.scalars(select(RefreshSession).order_by(RefreshSession.created_at))
            ).all()
            assert len(family_rows) == 2
            assert all(row.revoked_at is not None for row in family_rows)
        await engine.dispose()

    run(scenario())


def test_login_enforces_the_configured_active_session_bound() -> None:
    async def scenario() -> None:
        engine, sessions = await _database()
        settings = Settings(environment="test", max_active_sessions_per_user=1)
        now = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)

        async with sessions() as session:
            registration = await register_buyer(
                session,
                settings,
                email="buyer@example.com",
                display_name="Buyer",
                password="correct horse battery staple",
                now=now,
            )
            assert registration is not None
        async with sessions() as session:
            await verify_email(
                session,
                settings,
                raw_token=registration.verification_token,
                now=now + timedelta(seconds=1),
            )
        async with sessions() as session:
            first = await login(
                session,
                settings,
                email="buyer@example.com",
                password="correct horse battery staple",
                now=now + timedelta(seconds=2),
            )
        async with sessions() as session:
            second = await login(
                session,
                settings,
                email="buyer@example.com",
                password="correct horse battery staple",
                now=now + timedelta(seconds=3),
            )
        async with sessions() as session:
            with pytest.raises(InvalidSessionError):
                await authenticate_access_token(
                    session,
                    settings,
                    raw_token=first.access_token,
                    now=now + timedelta(seconds=4),
                )
            principal = await authenticate_access_token(
                session,
                settings,
                raw_token=second.access_token,
                now=now + timedelta(seconds=4),
            )
            assert principal.id == registration.user_id
        await engine.dispose()

    run(scenario())


def test_password_reset_revokes_sessions_and_replaces_credentials() -> None:
    async def scenario() -> None:
        engine, sessions = await _database()
        settings = Settings(environment="test")
        now = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)

        async with sessions() as session:
            registration = await register_buyer(
                session,
                settings,
                email="buyer@example.com",
                display_name="Buyer",
                password="original secure buyer password",
                now=now,
            )
            assert registration is not None
        async with sessions() as session:
            await verify_email(
                session,
                settings,
                raw_token=registration.verification_token,
                now=now + timedelta(seconds=1),
            )
        async with sessions() as session:
            authenticated = await login(
                session,
                settings,
                email="buyer@example.com",
                password="original secure buyer password",
                now=now + timedelta(seconds=2),
            )
        async with sessions() as session:
            reset_issue = await request_password_reset(
                session,
                settings,
                email="buyer@example.com",
                now=now + timedelta(seconds=3),
            )
            assert reset_issue is not None
        async with sessions() as session:
            await reset_password(
                session,
                settings,
                raw_token=reset_issue.reset_token,
                new_password="replacement secure buyer password",
                now=now + timedelta(seconds=4),
            )
        async with sessions() as session:
            with pytest.raises(InvalidSessionError):
                await authenticate_access_token(
                    session,
                    settings,
                    raw_token=authenticated.access_token,
                    now=now + timedelta(seconds=5),
                )
        async with sessions() as session:
            with pytest.raises(InvalidCredentialsError):
                await login(
                    session,
                    settings,
                    email="buyer@example.com",
                    password="original secure buyer password",
                    now=now + timedelta(seconds=6),
                )
        async with sessions() as session:
            replacement = await login(
                session,
                settings,
                email="buyer@example.com",
                password="replacement secure buyer password",
                now=now + timedelta(seconds=7),
            )
        async with sessions() as session:
            await logout(
                session,
                settings,
                raw_refresh_token=replacement.refresh_token,
                now=now + timedelta(seconds=8),
            )
        async with sessions() as session:
            with pytest.raises(InvalidSessionError):
                await authenticate_access_token(
                    session,
                    settings,
                    raw_token=replacement.access_token,
                    now=now + timedelta(seconds=9),
                )
        await engine.dispose()

    run(scenario())
