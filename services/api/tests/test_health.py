"""API foundation integration tests."""

from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from xxx_api.config import Settings
from xxx_api.main import create_app
from xxx_api.storage import ObjectStorageError


class HealthyRedis:
    async def ping(self) -> bool:
        return True


class UnhealthyRedis:
    async def ping(self) -> bool:
        raise RedisError


class HealthyStorage:
    async def check_ready(self) -> None:
        pass


class UnhealthyStorage:
    async def check_ready(self) -> None:
        raise ObjectStorageError


def test_liveness_has_stable_contract_and_request_id() -> None:
    client = TestClient(create_app(Settings(environment="test")))

    response = client.get("/health/live", headers={"X-Request-ID": "test-request-1"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"] == "test-request-1"


def test_readiness_fails_when_redis_is_unavailable() -> None:
    app = create_app(
        Settings(environment="test", database_url="sqlite+aiosqlite:///:memory:")
    )
    app.state.redis = UnhealthyRedis()
    client = TestClient(app)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Service not ready"}


def test_unsafe_request_id_is_replaced() -> None:
    client = TestClient(create_app(Settings(environment="test")))

    response = client.get("/health/live", headers={"X-Request-ID": "unsafe request id"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "unsafe request id"
    assert len(response.headers["X-Request-ID"]) == 32


def test_readiness_checks_configured_dependencies() -> None:
    app = create_app(
        Settings(environment="test", database_url="sqlite+aiosqlite:///:memory:")
    )
    app.state.redis = HealthyRedis()
    app.state.object_storage = HealthyStorage()
    client = TestClient(app)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_fails_when_private_storage_is_unavailable() -> None:
    app = create_app(
        Settings(environment="test", database_url="sqlite+aiosqlite:///:memory:")
    )
    app.state.redis = HealthyRedis()
    app.state.object_storage = UnhealthyStorage()
    client = TestClient(app)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Service not ready"}


def test_production_disables_interactive_docs() -> None:
    client = TestClient(
        create_app(
            Settings(
                environment="production",
                allowed_origins=["https://example.com"],
                secure_cookies=True,
                jwt_signing_secret="production-jwt-signing-secret-1234567890",
                token_hash_secret="production-token-hash-secret-0987654321",
                mfa_encryption_secret="production-mfa-encryption-secret-2468135790",
                storage_endpoint_url="https://storage.example.org",
                storage_access_key="production-storage-access",
                storage_secret_key="production-storage-secret",
                public_web_url="https://example.com",
                email_sender_address="no-reply@example.org",
                smtp_host="smtp.example.org",
                smtp_port=587,
                smtp_starttls=True,
            )
        )
    )

    assert client.get("/docs").status_code == 404
