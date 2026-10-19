"""The manual client verifies artifacts but cannot issue printer commands."""

from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from json import dumps
from pathlib import Path
from uuid import uuid4

import pytest

source = Path(__file__).resolve().parents[3] / "services/bridge/bridge.py"
spec = spec_from_file_location("manual_print_bridge", source)
module = module_from_spec(spec)
spec.loader.exec_module(module)


def package_fixture():
    authorization_id, item_id, result_id = str(uuid4()), str(uuid4()), str(uuid4())
    data = b"; LAB ONLY - not printable\n"
    digest = sha256(data).hexdigest()
    canonical = [{"position": 1, "sha256": digest, "quantity": 1, "resultId": result_id}]
    package = {
        "dispatchEnabled": False,
        "manifestSha256": sha256(
            dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "items": [
            {
                "id": item_id,
                **canonical[0],
                "downloadUrl": f"/api/v1/bridge/handoffs/{authorization_id}/artifacts/{item_id}",
            }
        ],
    }
    return authorization_id, package, data


def test_manual_bridge_verifies_bytes_acknowledges_and_never_overwrites(tmp_path):
    identifier, package, data = package_fixture()
    calls = []
    client = module.ManualBridge("http://127.0.0.1:8011", "fixture-credential")

    def request(path, body=None, *, binary=False):
        calls.append(path)
        if path.endswith("/claim"):
            return package
        return data if binary else None

    client.request = request
    paths = client.receive(identifier, tmp_path)
    assert paths[0].read_bytes() == data
    assert calls[-1].endswith("/received")
    assert not any("start" in call or "printer" in call for call in calls)
    with pytest.raises(FileExistsError):
        client.receive(identifier, tmp_path)


def test_manual_bridge_rejects_tampered_bytes_and_out_of_scope_urls(tmp_path):
    identifier, package, data = package_fixture()
    client = module.ManualBridge("http://127.0.0.1:8011")
    client.request = lambda path, body=None, binary=False: (
        package if path.endswith("/claim") else data + b"tampered"
    )
    with pytest.raises(ValueError, match="hash verification"):
        client.receive(identifier, tmp_path)
    package["items"][0]["downloadUrl"] = "https://another-host.example/artifact"
    with pytest.raises(ValueError, match="manifest item"):
        client.receive(identifier, tmp_path)
    with pytest.raises(ValueError, match="HTTPS"):
        module.ManualBridge("http://printer-lan.example")


def test_workflow_http_blocks_owner_operations_for_buyers_and_requires_csrf():
    from asyncio import run

    from fastapi.testclient import TestClient
    from test_owner_auth_http import BUYER_PASSWORD, ORIGIN, OWNER_PASSWORD, _build_app, _login

    app, engine, _sessions, _limiter = _build_app()
    with TestClient(app, base_url=ORIGIN) as client:
        _login(client, "buyer@example.com", BUYER_PASSWORD)
        assert client.get("/api/v1/owner/production").status_code == 403
        assert client.get("/api/v1/owner/bridges").status_code == 403
        hidden = client.get(f"/api/v1/orders/{uuid4()}")
        assert hidden.status_code == 404 and hidden.headers["Cache-Control"] == "no-store"
        assert client.post(f"/api/v1/quotations/{uuid4()}/accept", json={}).status_code == 403
        client.cookies.clear()
        _login(client, "owner@example.com", OWNER_PASSWORD)
        assert (
            client.post(
                "/api/v1/owner/bridges/pairing",
                json={"name": "fixture"},
                headers={"Origin": ORIGIN, "X-CSRF-Token": client.cookies.get("xxx_csrf")},
            ).status_code
            == 403
        )
    run(engine.dispose())


def test_bridge_http_pairs_and_consumes_download_in_fresh_database_sessions(tmp_path):
    from io import BytesIO

    from fastapi.testclient import TestClient
    from sqlalchemy import select
    from test_commerce import seed_commerce
    from test_workflow_safety import paid_job
    from workflow_lab import LabLimiter, LabStorage

    from xxx_api.config import Settings
    from xxx_api.main import create_app
    from xxx_api.models.analysis import AnalysisAssetResult
    from xxx_api.services.bridge import authorize_handoff, begin_pairing
    from xxx_api.services.commerce import complete_readiness, transition_job

    app = create_app(Settings(environment="test"))

    async def owner_pairing():
        async with sessions() as session:
            _bridge, token = await begin_pairing(session, owner, "LAB ONLY HTTP bridge")
            return token

    async def owner_authorization():
        async with sessions() as session:
            result = await session.scalar(select(AnalysisAssetResult))
            result.artifact_sha256 = sha256(LabStorage.data).hexdigest()
            await session.commit()
            job = await paid_job(session, owner, buyer, quote_request, estimate)
            await transition_job(
                session, owner=owner, job_id=job.id, expected_version=job.version, action="prepare"
            )
            await complete_readiness(
                session,
                owner=owner,
                job_id=job.id,
                expected_version=job.version,
                checklist={
                    key: True
                    for key in (
                        "bedClear",
                        "materialLoaded",
                        "nozzleChecked",
                        "areaClear",
                        "artifactReviewed",
                    )
                },
            )
            authorization = await authorize_handoff(session, owner, job.id, job.version)
            return str(authorization.id)

    with TestClient(app) as client:
        engine, sessions, owner, buyer, quote_request, estimate = client.portal.call(seed_commerce)
        client.portal.call(app.state.database_engine.dispose)
        app.state.object_storage.close()
        app.state.database_engine = engine
        app.state.session_factory = sessions
        app.state.rate_limiter = LabLimiter()
        app.state.object_storage = LabStorage()
        token = client.portal.call(owner_pairing)
        paired = client.post("/api/v1/bridge/pair", json={"token": token})
        assert paired.status_code == 200
        assert paired.json()["dispatchEnabled"] is False
        assert client.post("/api/v1/bridge/pair", json={"token": token}).status_code == 404
        credential = paired.json()["credential"]
        headers = {"Authorization": f"Bearer {credential}"}
        assert client.post("/api/v1/bridge/heartbeat", json={}, headers=headers).status_code == 200
        authorization_id = client.portal.call(owner_authorization)
        bridge = module.ManualBridge("http://127.0.0.1:8011", credential)

        class Opener:
            def open(self, request, timeout):
                response = client.request(
                    request.method,
                    request.full_url.replace(bridge.origin, ""),
                    content=request.data,
                    headers=dict(request.header_items()),
                )
                assert response.status_code == 200 or response.status_code == 204
                assert response.headers["Cache-Control"] == "no-store"
                return BytesIO(response.content)

        bridge.opener = Opener()
        paths = bridge.receive(authorization_id, tmp_path)
        assert paths[0].read_bytes() == LabStorage.data
        assert (
            client.post(
                f"/api/v1/bridge/handoffs/{authorization_id}/received", headers=headers
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"/api/v1/bridge/handoffs/{authorization_id}/claim", json={}, headers=headers
            ).status_code
            == 409
        )
