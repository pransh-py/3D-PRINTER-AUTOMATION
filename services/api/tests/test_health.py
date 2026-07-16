"""API foundation integration tests."""

from fastapi.testclient import TestClient

from xxx_api.config import Settings
from xxx_api.main import create_app


def test_liveness_has_stable_contract_and_request_id() -> None:
    client = TestClient(create_app(Settings(environment="test")))

    response = client.get("/health/live", headers={"X-Request-ID": "test-request-1"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"] == "test-request-1"


def test_unsafe_request_id_is_replaced() -> None:
    client = TestClient(create_app(Settings(environment="test")))

    response = client.get("/health/ready", headers={"X-Request-ID": "unsafe request id"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "unsafe request id"
    assert len(response.headers["X-Request-ID"]) == 32


def test_production_disables_interactive_docs() -> None:
    client = TestClient(
        create_app(
            Settings(
                environment="production",
                allowed_origins=["https://example.com"],
                secure_cookies=True,
                jwt_signing_secret="production-jwt-signing-secret-1234567890",
                token_hash_secret="production-token-hash-secret-0987654321",
            )
        )
    )

    assert client.get("/docs").status_code == 404
