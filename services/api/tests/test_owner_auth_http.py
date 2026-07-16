"""Owner-only HTTP, CSRF, MFA challenge, and recovery-code tests."""

from asyncio import run
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pyotp
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from xxx_api.config import Settings
from xxx_api.database import get_session
from xxx_api.dependencies import RecentMfaOwnerPrincipal
from xxx_api.main import create_app
from xxx_api.models import Base, RefreshSession
from xxx_api.rate_limit import RateLimitRule
from xxx_api.services.auth import register_buyer, verify_email
from xxx_api.services.owner_security import provision_owner

ORIGIN = "http://testserver"
OWNER_PASSWORD = "correct horse battery staple"
BUYER_PASSWORD = "another correct horse battery staple"


@dataclass
class AllowingRateLimiter:
    """Record owner-security rate-limit scopes without external Redis."""

    scopes: list[str] = field(default_factory=list)

    async def enforce(self, scope: str, rules: tuple[RateLimitRule, ...]) -> None:
        assert rules
        self.scopes.append(scope)


@dataclass
class NoopEmailSender:
    """Email is outside this owner-only HTTP scenario."""

    async def send_verification(self, recipient: str, raw_token: str) -> None:
        raise AssertionError("unexpected verification email")

    async def send_password_reset(self, recipient: str, raw_token: str) -> None:
        raise AssertionError("unexpected password reset email")


async def _create_database() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def _build_app() -> tuple[
    FastAPI,
    AsyncEngine,
    async_sessionmaker[AsyncSession],
    AllowingRateLimiter,
]:
    engine, sessions = run(_create_database())
    settings = Settings(environment="test", allowed_origins=[ORIGIN])

    async def seed() -> None:
        async with sessions() as session:
            await provision_owner(
                session,
                settings,
                email="owner@example.com",
                display_name="Owner",
                password=OWNER_PASSWORD,
            )
        async with sessions() as session:
            buyer = await register_buyer(
                session,
                settings,
                email="buyer@example.com",
                display_name="Buyer",
                password=BUYER_PASSWORD,
            )
            assert buyer is not None
        async with sessions() as session:
            await verify_email(session, settings, raw_token=buyer.verification_token)

    run(seed())
    app = create_app(settings)

    @app.get("/api/v1/test/recent-owner")
    async def recent_owner_gate(_principal: RecentMfaOwnerPrincipal) -> dict[str, bool]:
        return {"allowed": True}

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    limiter = AllowingRateLimiter()
    app.state.rate_limiter = limiter
    app.state.email_sender = NoopEmailSender()
    return app, engine, sessions, limiter


def _login(client: TestClient, email: str, password: str):
    return client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN},
        json={"email": email, "password": password},
    )


def test_owner_mfa_http_flow_requires_role_csrf_and_second_factor() -> None:
    app, engine, sessions, limiter = _build_app()
    with TestClient(app, base_url=ORIGIN) as client:
        buyer_login = _login(client, "buyer@example.com", BUYER_PASSWORD)
        assert buyer_login.status_code == 200
        assert client.get("/api/v1/auth/mfa").status_code == 403
        client.cookies.clear()

        owner_login = _login(client, "owner@example.com", OWNER_PASSWORD)
        assert owner_login.status_code == 200
        assert client.get("/api/v1/auth/mfa").json() == {"enabled": False}
        assert client.get("/api/v1/test/recent-owner").status_code == 403

        missing_csrf = client.post(
            "/api/v1/auth/mfa/totp/enroll",
            headers={"Origin": ORIGIN},
            json={"currentPassword": OWNER_PASSWORD},
        )
        assert missing_csrf.status_code == 403
        csrf = client.cookies.get("xxx_csrf")
        assert csrf is not None
        wrong_password = client.post(
            "/api/v1/auth/mfa/totp/enroll",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            json={"currentPassword": "wrong password"},
        )
        assert wrong_password.status_code == 401
        enrollment = client.post(
            "/api/v1/auth/mfa/totp/enroll",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            json={"currentPassword": OWNER_PASSWORD},
        )
        assert enrollment.status_code == 200
        secret = enrollment.json()["secret"]
        assert enrollment.json()["provisioningUri"].startswith("otpauth://totp/")
        confirmation = client.post(
            "/api/v1/auth/mfa/totp/confirm",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            json={"code": pyotp.TOTP(secret).now()},
        )
        assert confirmation.status_code == 200
        recovery_codes = confirmation.json()["recoveryCodes"]
        assert len(recovery_codes) == 10
        assert client.get("/api/v1/auth/mfa").json() == {"enabled": True}
        assert client.get("/api/v1/test/recent-owner").json() == {"allowed": True}

        async def expire_recent_mfa() -> None:
            async with sessions() as session:
                await session.execute(
                    update(RefreshSession)
                    .where(RefreshSession.mfa_authenticated_at.is_not(None))
                    .values(mfa_authenticated_at=datetime(2000, 1, 1, tzinfo=UTC))
                )
                await session.commit()

        run(expire_recent_mfa())
        assert client.get("/api/v1/test/recent-owner").status_code == 403

        client.cookies.clear()
        challenged = _login(client, "owner@example.com", OWNER_PASSWORD)
        assert challenged.status_code == 202
        assert challenged.json()["mfaRequired"] is True
        assert "accessToken" not in challenged.text
        assert not challenged.headers.get_list("set-cookie")
        challenge = challenged.json()["challenge"]
        invalid = client.post(
            "/api/v1/auth/login/mfa",
            headers={"Origin": ORIGIN},
            json={"challenge": challenge, "code": "000000"},
        )
        assert invalid.status_code == 401
        recovered = client.post(
            "/api/v1/auth/login/mfa",
            headers={"Origin": ORIGIN},
            json={"challenge": challenge, "code": recovery_codes[0]},
        )
        assert recovered.status_code == 200
        assert recovered.json()["role"] == "owner"
        assert client.cookies.get("xxx_access") is not None
        replay = client.post(
            "/api/v1/auth/login/mfa",
            headers={"Origin": ORIGIN},
            json={"challenge": challenge, "code": recovery_codes[0]},
        )
        assert replay.status_code == 401
        assert {"owner-mfa-enroll", "owner-mfa-confirm", "login-mfa"}.issubset(limiter.scopes)

    run(engine.dispose())
