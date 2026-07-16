"""Quote HTTP authorization, CSRF, private response, and upload flow tests."""

from asyncio import run
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from xxx_api.config import Settings
from xxx_api.database import get_session
from xxx_api.main import create_app
from xxx_api.models import Base
from xxx_api.rate_limit import RateLimitRule
from xxx_api.services.auth import register_buyer, verify_email
from xxx_api.services.owner_security import provision_owner
from xxx_api.storage import ObjectMetadata, ObjectNotFoundError, PresignedPost

ORIGIN = "http://testserver"
PASSWORD = "correct horse battery staple"


@dataclass
class AllowingRateLimiter:
    scopes: list[str] = field(default_factory=list)

    async def enforce(self, scope: str, rules: tuple[RateLimitRule, ...]) -> None:
        assert rules
        self.scopes.append(scope)


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, ObjectMetadata] = {}
        self.uploads: list[tuple[str, dict[str, str]]] = []

    async def create_upload(
        self,
        *,
        key: str,
        size_bytes: int,
        content_type: str,
        metadata: dict[str, str],
    ) -> PresignedPost:
        self.uploads.append((key, metadata))
        return PresignedPost(
            url="http://storage.test/xxx-private-models",
            fields={
                "key": key,
                "Content-Type": content_type,
                **{f"x-amz-meta-{name}": value for name, value in metadata.items()},
            },
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )

    async def head(self, key: str) -> ObjectMetadata:
        try:
            return self.objects[key]
        except KeyError as error:
            raise ObjectNotFoundError from error

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    async def check_ready(self) -> None:
        pass

    def close(self) -> None:
        pass


async def _database() -> tuple[object, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def _build_app():
    engine, sessions = run(_database())
    settings = Settings(environment="test", allowed_origins=[ORIGIN])

    async def seed() -> None:
        for email in ("first@example.com", "second@example.com"):
            async with sessions() as session:
                issue = await register_buyer(
                    session,
                    settings,
                    email=email,
                    display_name=email.split("@", maxsplit=1)[0],
                    password=PASSWORD,
                )
                assert issue is not None
            async with sessions() as session:
                await verify_email(session, settings, raw_token=issue.verification_token)
        async with sessions() as session:
            await provision_owner(
                session,
                settings,
                email="owner@example.com",
                display_name="Owner",
                password=PASSWORD,
            )

    run(seed())
    app = create_app(settings)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    limiter = AllowingRateLimiter()
    storage = FakeStorage()
    app.state.rate_limiter = limiter
    app.state.object_storage = storage
    return app, engine, limiter, storage


def _login(client: TestClient, email: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN},
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200


def _csrf(client: TestClient) -> dict[str, str]:
    value = client.cookies.get("xxx_csrf")
    assert value is not None
    return {"Origin": ORIGIN, "X-CSRF-Token": value}


def test_private_quote_upload_http_flow_and_cross_buyer_concealment() -> None:
    app, engine, limiter, storage = _build_app()
    with TestClient(app, base_url=ORIGIN) as first:
        _login(first, "first@example.com")
        missing_csrf = first.post(
            "/api/v1/quote-requests",
            headers={"Origin": ORIGIN},
            json={"clientToken": str(uuid4())},
        )
        assert missing_csrf.status_code == 403
        created = first.post(
            "/api/v1/quote-requests",
            headers=_csrf(first),
            json={"clientToken": str(uuid4())},
        )
        assert created.status_code == 201
        assert created.headers["cache-control"] == "no-store"
        quote_id = created.json()["id"]
        digest = "c" * 64
        intent = first.post(
            f"/api/v1/quote-requests/{quote_id}/uploads",
            headers=_csrf(first),
            json={
                "clientToken": str(uuid4()),
                "filename": "bracket.step",
                "sizeBytes": 2048,
                "sha256": digest,
            },
        )
        assert intent.status_code == 201
        asset_id = intent.json()["asset"]["id"]
        key, metadata = storage.uploads[-1]
        storage.objects[key] = ObjectMetadata(
            size_bytes=2048,
            content_type="application/octet-stream",
            metadata=metadata,
            etag='"etag"',
        )
        completed = first.post(
            f"/api/v1/quote-requests/{quote_id}/uploads/{asset_id}/complete",
            headers=_csrf(first),
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "quarantined"
        submitted = first.post(
            f"/api/v1/quote-requests/{quote_id}/submit",
            headers=_csrf(first),
        )
        assert submitted.status_code == 200
        assert submitted.json()["status"] == "analyzing"
        ordinary = first.get(f"/api/v1/quote-requests/{quote_id}")
        assert ordinary.status_code == 200
        assert key not in ordinary.text

    with TestClient(app, base_url=ORIGIN) as second:
        _login(second, "second@example.com")
        assert second.get(f"/api/v1/quote-requests/{quote_id}").status_code == 404

    with TestClient(app, base_url=ORIGIN) as owner:
        _login(owner, "owner@example.com")
        assert owner.get(f"/api/v1/quote-requests/{quote_id}").status_code == 200
        denied = owner.post(
            "/api/v1/quote-requests",
            headers=_csrf(owner),
            json={"clientToken": str(uuid4())},
        )
        assert denied.status_code == 403
    assert {"quote-request-create", "model-upload-issue"}.issubset(limiter.scopes)
    run(engine.dispose())
