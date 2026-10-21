"""The local adapter accepts real bytes without exposing a public file directory."""

from asyncio import run
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from test_quotes_http import PASSWORD, _build_app
from xxx_api.config import Settings
from xxx_api.database import get_session
from xxx_api.domain.quotes import ModelAssetStatus
from xxx_api.local_storage import LocalObjectStorage
from xxx_api.models.quotes import ModelAsset
from xxx_api.storage import ObjectNotFoundError, ObjectStorageError


async def chunks(data):
    yield data[:4]
    yield data[4:]


def test_local_upload_is_private_bounded_and_downloadable_by_worker(tmp_path):
    async def scenario():
        settings = Settings(
            _env_file=None,
            environment="test",
            storage_backend="local",
            storage_local_directory=tmp_path / "objects",
        )
        storage = LocalObjectStorage(settings)
        data = b"a real private model body"
        digest = sha256(data).hexdigest()
        await storage.receive(
            "private-source",
            chunks(data),
            expected_size=len(data),
            expected_sha256=digest,
            metadata={"asset-id": "test", "sha256": digest},
        )
        observed = await storage.head("private-source")
        assert observed.size_bytes == len(data)
        destination = tmp_path / "worker-input"
        assert await storage.download_to_path("private-source", destination, max_bytes=100) == len(
            data
        )
        assert destination.read_bytes() == data
        with pytest.raises(ObjectStorageError):
            await storage.receive(
                "private-source",
                chunks(data),
                expected_size=len(data),
                expected_sha256=digest,
                metadata={},
            )

    run(scenario())


@pytest.mark.parametrize(
    "body,size,digest", [(b"too long", 1, "a" * 64), (b"bad hash", 8, "a" * 64)]
)
def test_rejected_local_bodies_leave_no_complete_object(tmp_path, body, size, digest):
    async def scenario():
        storage = LocalObjectStorage(
            Settings(
                _env_file=None,
                environment="test",
                storage_backend="local",
                storage_local_directory=tmp_path / "objects",
            )
        )
        with pytest.raises(ObjectStorageError):
            await storage.receive(
                "source", chunks(body), expected_size=size, expected_sha256=digest, metadata={}
            )
        with pytest.raises(ObjectNotFoundError):
            await storage.head("source")

    run(scenario())


def test_local_storage_cannot_be_enabled_for_staging_or_public_web(tmp_path):
    for environment, origin in [
        ("staging", "http://localhost:3000"),
        ("development", "https://store.example.com"),
    ]:
        with pytest.raises(ValueError):
            Settings(
                _env_file=None,
                environment=environment,
                storage_backend="local",
                storage_local_directory=tmp_path,
                public_web_url=origin,
            )


def test_trusted_lan_storage_is_explicit_and_scoped_to_one_origin(tmp_path):
    base = dict(
        _env_file=None,
        environment="development",
        storage_backend="local",
        storage_local_directory=tmp_path / "lan-objects",
        public_web_url="http://10.31.68.160:3100",
        allowed_origins=["http://10.31.68.160:3100", "http://localhost:3100"],
    )
    with pytest.raises(ValueError, match="loopback-only"):
        Settings(**base)
    settings = Settings(**base, storage_local_lan_origin="http://10.31.68.160:3100")
    assert LocalObjectStorage(settings).root == tmp_path / "lan-objects"
    for origin in ["http://10.31.68.161:3100", "http://10.31.68.160:3101", "https://example.com"]:
        with pytest.raises(ValueError, match="loopback-only"):
            Settings(
                **{**base, "allowed_origins": [origin]},
                storage_local_lan_origin="http://10.31.68.160:3100",
            )
    for origin in [
        "http://8.8.8.8:3100",
        "http://localhost:3100",
        "http://169.254.1.1:3100",
        "http://10.31.68.160:3100/path",
        "http://user@10.31.68.160:3100",
        "http://10.31.68.160:3100/?x=1",
    ]:
        with pytest.raises(ValueError, match="RFC1918"):
            Settings(**base, storage_local_lan_origin=origin)
    for environment in ["staging", "production"]:
        with pytest.raises(ValueError, match="development/test-only"):
            Settings(
                **{**base, "environment": environment},
                storage_local_lan_origin="http://10.31.68.160:3100",
            )


def test_real_http_upload_requires_session_csrf_owner_size_and_checksum(tmp_path):
    app, engine, _, _ = _build_app()
    origin = "http://localhost:3000"
    settings = Settings(
        _env_file=None,
        environment="test",
        storage_backend="local",
        storage_local_directory=tmp_path / "private-objects",
        public_web_url=origin,
        allowed_origins=[origin],
    )
    app.state.settings = settings
    app.state.object_storage.close()
    app.state.object_storage = LocalObjectStorage(settings)
    data = b"solid sample\nendsolid sample\n"
    with TestClient(app, base_url=origin, client=("127.0.0.1", 50000)) as client:
        logged_in = client.post(
            "/api/v1/auth/login",
            headers={"Origin": origin},
            json={"email": "first@example.com", "password": PASSWORD},
        )
        assert logged_in.status_code == 200
        csrf = {"Origin": origin, "X-CSRF-Token": client.cookies.get("xxx_csrf")}
        quote = client.post(
            "/api/v1/quote-requests", headers=csrf, json={"clientToken": str(uuid4())}
        )
        assert quote.status_code == 201
        request_id = quote.json()["id"]
        intent = client.post(
            f"/api/v1/quote-requests/{request_id}/uploads",
            headers=csrf,
            json={
                "clientToken": str(uuid4()),
                "filename": "sample.stl",
                "sizeBytes": len(data),
                "sha256": sha256(data).hexdigest(),
            },
        )
        assert intent.status_code == 201
        upload = intent.json()["upload"]
        assert upload["method"] == "PUT" and upload["url"].startswith("/api/v1/")
        assert (
            client.put(upload["url"], content=data, headers={"Origin": origin}).status_code == 403
        )
        headers = {**csrf, "Content-Type": "application/octet-stream"}
        assert (
            client.put(upload["url"], content=data + b"extra", headers=headers).status_code == 413
        )
        assert (
            client.put(upload["url"], content=b"x" * len(data), headers=headers).status_code == 422
        )
        assert client.put(upload["url"], content=data, headers=headers).status_code == 204
        asset_id = intent.json()["asset"]["id"]
        completed = client.post(
            f"/api/v1/quote-requests/{request_id}/uploads/{asset_id}/complete", headers=csrf
        )
        assert completed.status_code == 200 and completed.json()["status"] == "quarantined"
        assert str(settings.storage_local_directory) not in completed.text
        assert client.get(upload["url"]).status_code == 405
        assert (
            client.post(
                "/api/v1/auth/login",
                headers={"Origin": origin},
                json={"email": "second@example.com", "password": PASSWORD},
            ).status_code
            == 200
        )
        other = {
            "Origin": origin,
            "Content-Type": "application/octet-stream",
            "X-CSRF-Token": client.cookies.get("xxx_csrf"),
        }
        assert client.put(upload["url"], content=data, headers=other).status_code == 404
        model_url = f"/api/v1/owner/quote-requests/{request_id}/models/{asset_id}"
        assert client.get(model_url).status_code == 403
        assert (
            client.post(
                "/api/v1/auth/login",
                headers={"Origin": origin},
                json={"email": "owner@example.com", "password": PASSWORD},
            ).status_code
            == 200
        )
        assert client.get(model_url).status_code == 404  # Quarantine is not downloadable.

        async def validate_fixture():
            async for session in app.dependency_overrides[get_session]():
                asset = await session.get(ModelAsset, UUID(asset_id))
                asset.status = ModelAssetStatus.VALIDATED
                asset.verified_sha256 = sha256(data).hexdigest()
                await session.commit()

        client.portal.call(validate_fixture)
        reviewed = client.get(model_url)
        assert reviewed.status_code == 200 and reviewed.content == data
        assert reviewed.headers["Cache-Control"] == "no-store"
        assert reviewed.headers["Content-Disposition"].startswith("attachment;")
        assert client.get(model_url.replace(request_id, str(uuid4()))).status_code == 404
    run(engine.dispose())
