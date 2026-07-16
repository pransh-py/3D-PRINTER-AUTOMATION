"""Identity HTTP contract, cookie, origin, CSRF, and anti-enumeration tests."""

from asyncio import run
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from xxx_api.config import Settings
from xxx_api.database import get_session
from xxx_api.email import EmailDeliveryError
from xxx_api.main import create_app
from xxx_api.models import Base
from xxx_api.rate_limit import RateLimitRule

ORIGIN = "http://testserver"


@dataclass
class CapturingEmailSender:
    """Capture raw one-time tokens only inside the test delivery boundary."""

    verification_tokens: list[tuple[str, str]] = field(default_factory=list)
    reset_tokens: list[tuple[str, str]] = field(default_factory=list)
    fail_delivery: bool = False

    async def send_verification(self, recipient: str, raw_token: str) -> None:
        if self.fail_delivery:
            raise EmailDeliveryError
        self.verification_tokens.append((recipient, raw_token))

    async def send_password_reset(self, recipient: str, raw_token: str) -> None:
        if self.fail_delivery:
            raise EmailDeliveryError
        self.reset_tokens.append((recipient, raw_token))


@dataclass
class AllowingRateLimiter:
    """Record that each endpoint reached the shared limiter boundary."""

    scopes: list[str] = field(default_factory=list)

    async def enforce(self, scope: str, rules: tuple[RateLimitRule, ...]) -> None:
        assert rules
        self.scopes.append(scope)


async def _create_database() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def _build_app() -> tuple[FastAPI, AsyncEngine, CapturingEmailSender, AllowingRateLimiter]:
    engine, sessions = run(_create_database())
    app = create_app(Settings(environment="test", allowed_origins=[ORIGIN]))

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    sender = CapturingEmailSender()
    limiter = AllowingRateLimiter()
    app.state.email_sender = sender
    app.state.rate_limiter = limiter
    return app, engine, sender, limiter


def _register(client: TestClient, email: str = "buyer@example.com") -> str:
    response = client.post(
        "/api/v1/auth/register",
        headers={"Origin": ORIGIN},
        json={
            "email": email,
            "displayName": "Buyer",
            "password": "correct horse battery staple",
        },
    )
    assert response.status_code == 202
    assert "token" not in response.text.lower()
    return email


def test_identity_http_flow_keeps_bearers_out_of_bodies_and_enforces_csrf() -> None:
    app, engine, sender, limiter = _build_app()
    with TestClient(app, base_url=ORIGIN) as client:
        missing_origin = client.post(
            "/api/v1/auth/register",
            json={
                "email": "buyer@example.com",
                "displayName": "Buyer",
                "password": "correct horse battery staple",
            },
        )
        assert missing_origin.status_code == 403

        owner_injection = client.post(
            "/api/v1/auth/register",
            headers={"Origin": ORIGIN},
            json={
                "email": "owner@example.com",
                "displayName": "Injected Owner",
                "password": "correct horse battery staple",
                "role": "owner",
            },
        )
        assert owner_injection.status_code == 422

        _register(client)
        assert len(sender.verification_tokens) == 1
        verification_token = sender.verification_tokens[0][1]

        duplicate = client.post(
            "/api/v1/auth/register",
            headers={"Origin": ORIGIN},
            json={
                "email": "BUYER@example.com",
                "displayName": "Someone Else",
                "password": "another secure buyer password",
            },
        )
        assert duplicate.status_code == 202
        assert len(sender.verification_tokens) == 1

        pending_login = client.post(
            "/api/v1/auth/login",
            headers={"Origin": ORIGIN},
            json={
                "email": "buyer@example.com",
                "password": "correct horse battery staple",
            },
        )
        assert pending_login.status_code == 403

        verified = client.post(
            "/api/v1/auth/verify-email",
            headers={"Origin": ORIGIN},
            json={"token": verification_token},
        )
        assert verified.status_code == 200

        authenticated = client.post(
            "/api/v1/auth/login",
            headers={"Origin": ORIGIN},
            json={
                "email": "buyer@example.com",
                "password": "correct horse battery staple",
            },
        )
        assert authenticated.status_code == 200
        assert authenticated.json()["email"] == "buyer@example.com"
        assert "accessToken" not in authenticated.text
        set_cookies = authenticated.headers.get_list("set-cookie")
        assert any("xxx_access=" in value and "HttpOnly" in value for value in set_cookies)
        assert any("xxx_refresh=" in value and "HttpOnly" in value for value in set_cookies)
        assert any("xxx_csrf=" in value and "HttpOnly" not in value for value in set_cookies)

        current = client.get("/api/v1/auth/me")
        assert current.status_code == 200
        assert current.headers["Cache-Control"] == "no-store"

        csrf_token = client.cookies.get("xxx_csrf")
        assert csrf_token is not None
        refreshed = client.post(
            "/api/v1/auth/refresh",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_token},
        )
        assert refreshed.status_code == 204
        replacement_csrf = client.cookies.get("xxx_csrf")
        assert replacement_csrf is not None
        assert replacement_csrf != csrf_token

        rejected_refresh = client.post(
            "/api/v1/auth/refresh",
            headers={"Origin": ORIGIN, "X-CSRF-Token": "wrong-token"},
        )
        assert rejected_refresh.status_code == 401
        assert client.get("/api/v1/auth/me").status_code == 401
        assert {"register", "login", "verify-email", "refresh"}.issubset(limiter.scopes)

    run(engine.dispose())


def test_password_reset_is_generic_and_revokes_existing_sessions() -> None:
    app, engine, sender, _limiter = _build_app()
    with TestClient(app, base_url=ORIGIN) as client:
        _register(client)
        verification_token = sender.verification_tokens[0][1]
        assert (
            client.post(
                "/api/v1/auth/verify-email",
                headers={"Origin": ORIGIN},
                json={"token": verification_token},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/v1/auth/login",
                headers={"Origin": ORIGIN},
                json={
                    "email": "buyer@example.com",
                    "password": "correct horse battery staple",
                },
            ).status_code
            == 200
        )

        unknown = client.post(
            "/api/v1/auth/forgot-password",
            headers={"Origin": ORIGIN},
            json={"email": "unknown@example.com"},
        )
        known = client.post(
            "/api/v1/auth/forgot-password",
            headers={"Origin": ORIGIN},
            json={"email": "buyer@example.com"},
        )
        assert unknown.status_code == known.status_code == 202
        assert unknown.json() == known.json()
        assert len(sender.reset_tokens) == 1

        reset = client.post(
            "/api/v1/auth/reset-password",
            headers={"Origin": ORIGIN},
            json={
                "token": sender.reset_tokens[0][1],
                "newPassword": "replacement secure buyer password",
            },
        )
        assert reset.status_code == 200
        assert client.get("/api/v1/auth/me").status_code == 401

        old_credentials = client.post(
            "/api/v1/auth/login",
            headers={"Origin": ORIGIN},
            json={
                "email": "buyer@example.com",
                "password": "correct horse battery staple",
            },
        )
        assert old_credentials.status_code == 401
        new_credentials = client.post(
            "/api/v1/auth/login",
            headers={"Origin": ORIGIN},
            json={
                "email": "buyer@example.com",
                "password": "replacement secure buyer password",
            },
        )
        assert new_credentials.status_code == 200

        csrf_token = client.cookies.get("xxx_csrf")
        assert csrf_token is not None
        logged_out = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_token},
        )
        assert logged_out.status_code == 204
        assert client.get("/api/v1/auth/me").status_code == 401

    run(engine.dispose())


def test_email_provider_failure_does_not_reveal_registration_eligibility() -> None:
    app, engine, sender, _limiter = _build_app()
    sender.fail_delivery = True

    with TestClient(app, base_url=ORIGIN) as client:
        new_account = client.post(
            "/api/v1/auth/register",
            headers={"Origin": ORIGIN},
            json={
                "email": "buyer@example.com",
                "displayName": "Buyer",
                "password": "correct horse battery staple",
            },
        )
        existing_account = client.post(
            "/api/v1/auth/register",
            headers={"Origin": ORIGIN},
            json={
                "email": "buyer@example.com",
                "displayName": "Buyer",
                "password": "correct horse battery staple",
            },
        )

        assert new_account.status_code == existing_account.status_code == 202
        assert new_account.json() == existing_account.json()

    run(engine.dispose())
