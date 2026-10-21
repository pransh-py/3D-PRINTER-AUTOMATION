"""Free measured submissions never create commercial orders or payment records."""

from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_commerce import seed_commerce
from test_station_dispatch import event, run_case

from xxx_api.models.analysis import AnalysisAssetResult, AnalysisRun
from xxx_api.models.commerce import Order, PaymentIntent
from xxx_api.models.presentation import PresentationEntry, PresentationStation
from xxx_api.models.quotes import QuoteRequest
from xxx_api.schemas.commerce import DispatchEventInput, ReadinessInput
from xxx_api.services import presentation as service
from xxx_api.services.bridge import begin_pairing, finish_pairing
from xxx_api.services.commerce import WorkflowConflictError, WorkflowNotFoundError, utc


@asynccontextmanager
async def scenario():
    engine, sessions, owner, buyer, request, estimate = await seed_commerce()
    try:
        async with sessions() as session:
            request = await session.get(QuoteRequest, request.id)
            request.print_specification = {
                "presetCode": "lab-pla",
                "presetLabel": "Fixture PLA",
                "materialCode": "lab-pla",
                "profileSha256": "b" * 64,
                "colour": "red",
                "settings": {},
            }
            analysis = await session.scalar(select(AnalysisRun))
            analysis.print_preset_code = "lab-pla"
            result = await session.scalar(select(AnalysisAssetResult))
            result.fits_build_volume = True
            session.add(PresentationStation(id=1, version=1, state="offline"))
            await session.commit()
            bridge, token = await begin_pairing(session, owner, "Loopback fixture")
            bridge, _ = await finish_pairing(session, token, adapter="station-zmod-v1")
            yield session, owner, buyer, request, estimate, bridge
    finally:
        await engine.dispose()


def readiness(version):
    return ReadinessInput(
        expectedVersion=version,
        bedClear=True,
        materialLoaded=True,
        nozzleChecked=True,
        areaClear=True,
        artifactReviewed=True,
    )


@run_case
async def test_admission_is_fifo_and_completion_does_not_clear_the_next_plate():
    from sqlalchemy import inspect

    from xxx_api.models.pricing import QuoteEstimate
    from xxx_api.models.quotes import ModelAsset

    def clone(row, **changes):
        values = {
            column.key: getattr(row, column.key)
            for column in inspect(type(row)).columns
            if column.key not in {"id", "created_at", "updated_at"}
        }
        return type(row)(**{**values, "id": uuid4(), **changes})

    async with scenario() as (session, owner, buyer, request, estimate, bridge):
        estimate = await session.get(QuoteEstimate, estimate.id)
        analysis = await session.scalar(select(AnalysisRun))
        asset = await session.scalar(select(ModelAsset))
        result = await session.scalar(select(AnalysisAssetResult))
        second_request = clone(request, client_token=uuid4())
        second_asset = clone(asset, quote_request_id=second_request.id, client_token=uuid4(),
                             storage_key="lab/second-source")
        second_analysis = clone(analysis, quote_request_id=second_request.id)
        second_result = clone(
            result, analysis_run_id=second_analysis.id, model_asset_id=second_asset.id
        )
        second_estimate = clone(
            estimate,
            quote_request_id=second_request.id,
            analysis_run_id=second_analysis.id,
            client_token=uuid4(),
        )
        session.add_all(
            [second_request, second_asset, second_analysis, second_result, second_estimate]
        )
        await session.commit()
        first = await service.submit(session, buyer, request.id, estimate.id, request.version)
        second = await service.submit(
            session, buyer, second_request.id, second_estimate.id, second_request.version
        )
        first = await service.admit(session, owner, first, first.version)
        second = await service.admit(session, owner, second, second.version)
        await service.heartbeat(session, bridge, "ready")
        with pytest.raises(WorkflowConflictError):
            await service.clear_bed(session, owner, second, readiness(second.version))
        await service.clear_bed(session, owner, first, readiness(first.version))
        first = await service.claim(session, bridge, first.id)
        with pytest.raises(WorkflowConflictError):
            await service.claim(session, bridge, second.id)
        first = await service.record_event(
            session, bridge, first, DispatchEventInput(**event("sent"))
        )
        await service.record_event(session, bridge, first, DispatchEventInput(**event("completed")))
        assert (await service.head(session)).id == second.id
        assert await service.grants(session) == []
        await service.clear_bed(session, owner, second, readiness(second.version))
        assert (await service.grants(session))[0]["id"] == str(second.id)


@run_case
async def test_explicit_free_submission_and_owner_admission_no_payment():
    async with scenario() as (session, owner, buyer, request, estimate, _):
        assert await session.scalar(select(func.count()).select_from(PresentationEntry)) == 0
        row = await service.submit(session, buyer, request.id, estimate.id, request.version)
        assert row.status == "waiting"
        assert (
            await service.submit(session, buyer, request.id, estimate.id, request.version)
        ).id == row.id
        assert await service.grants(session) == []
        with pytest.raises(WorkflowNotFoundError):
            await service.admit(session, buyer, row, row.version)
        row = await service.admit(session, owner, row, row.version)
        assert row.status == "approved"
        with pytest.raises(WorkflowConflictError):
            await service.admit(session, owner, row, 1)
        view = await service.public_entry(session, row)
        assert view["free"] is True and view["referenceCostPaise"] == estimate.total_paise
        assert view["durationSeconds"] == 1800 and view["filenames"] == ["lab.stl"]
        for model in (Order, PaymentIntent):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


@run_case
async def test_dispatch_needs_fresh_single_use_clearance_and_does_not_retry():
    async with scenario() as (session, owner, buyer, request, estimate, bridge):
        row = await service.submit(session, buyer, request.id, estimate.id, request.version)
        row = await service.admit(session, owner, row, row.version)
        with pytest.raises(WorkflowConflictError):
            await service.claim(session, bridge, row.id)
        with pytest.raises(WorkflowConflictError):
            await service.clear_bed(session, owner, row, readiness(row.version))
        await service.heartbeat(session, bridge, "ready")
        await service.clear_bed(session, owner, row, readiness(row.version))
        state = await service.station(session)
        state.cleared_at = utc() - timedelta(minutes=6)
        await session.commit()
        assert await service.grants(session) == []
        await service.clear_bed(session, owner, row, readiness(row.version))
        assert await service.grants(session) == [{"id": str(row.id), "jobId": str(row.id)}]
        row = await service.claim(session, bridge, row.id)
        assert row.status == "claimed"
        assert (await service.claim(session, bridge, row.id)).id == row.id
        assert await service.grants(session) == []
        with pytest.raises(WorkflowConflictError):
            await service.record_event(
                session, bridge, row, DispatchEventInput(**event("completed"))
            )
        sent = DispatchEventInput(**event("sent"))
        row = await service.record_event(session, bridge, row, sent)
        row = await service.record_event(session, bridge, row, sent)
        assert len(row.events) == 1
        with pytest.raises(WorkflowConflictError):
            await service.record_event(
                session, bridge, row, sent.model_copy(update={"dispatch_sha256": "e" * 64})
            )
        row = await service.record_event(
            session, bridge, row, DispatchEventInput(**event("printing"))
        )
        with pytest.raises(WorkflowConflictError):
            await service.record_event(
                session, bridge, row, DispatchEventInput(**event("awaiting_start"))
            )
        row = await service.record_event(
            session, bridge, row, DispatchEventInput(**event("completed"))
        )
        assert row.status == "completed"
        assert (await service.station(session)).active_entry_id is None
        assert (await service.station(session)).clear_entry_id is None
        with pytest.raises(WorkflowConflictError):
            await service.claim(session, bridge, row.id)


@run_case
@pytest.mark.parametrize("change", ["quantity", "expiry", "hash", "profile", "version", "material"])
async def test_mismatched_evidence_never_enters_queue(change):
    async with scenario() as (session, _, buyer, request, estimate, _bridge):
        from xxx_api.models.pricing import QuoteEstimate

        estimate = await session.get(QuoteEstimate, estimate.id)
        result = await session.scalar(select(AnalysisAssetResult))
        analysis = await session.scalar(select(AnalysisRun))
        if change == "quantity":
            request.quantity = 2
        if change == "expiry":
            estimate.expires_at = utc() - timedelta(seconds=1)
        if change == "hash":
            result.verified_sha256 = "f" * 64
        if change == "profile":
            analysis.profile_sha256 = "f" * 64
        if change == "material":
            analysis.material_code = "petg"
        if change == "version":
            request.version += 1
        await session.commit()
        with pytest.raises(WorkflowConflictError):
            await service.submit(session, buyer, request.id, estimate.id, request.version)
        assert await session.scalar(select(func.count()).select_from(PresentationEntry)) == 0


@run_case
async def test_buyer_cannot_access_another_buyers_entry_and_manual_bridge_cannot_claim():
    async with scenario() as (session, _, buyer, request, estimate, bridge):
        row = await service.submit(session, buyer, request.id, estimate.id, request.version)
        original = buyer.id
        buyer.id = uuid4()
        with pytest.raises(WorkflowNotFoundError):
            await service.entry(session, row.id, buyer)
        buyer.id = original
        bridge.adapter_name = "manual-orca"
        with pytest.raises(WorkflowNotFoundError):
            await service.claim(session, bridge, row.id)


def test_free_mode_is_explicit_and_not_a_production_payment_bypass():
    from pydantic import ValidationError

    from xxx_api.config import Settings

    with pytest.raises(ValidationError, match="presentation"):
        Settings(_env_file=None, environment="production", presentation_mode=True)


def test_free_app_does_not_mount_commercial_order_endpoints():
    from fastapi.testclient import TestClient

    from xxx_api.config import Settings
    from xxx_api.main import create_app
    with TestClient(create_app(Settings(environment="test", presentation_mode=True))) as client:
        assert client.get("/api/v1/orders").status_code == 404


def test_http_queue_keeps_real_auth_csrf_roles_and_operator_mfa():
    from asyncio import run

    from fastapi.testclient import TestClient
    from test_owner_auth_http import BUYER_PASSWORD, ORIGIN, OWNER_PASSWORD, _build_app, _login

    app, engine, sessions, _ = _build_app()
    app.state.settings.presentation_mode = True

    async def seed():
        async with sessions() as session:
            session.add(PresentationStation(id=1, version=1, state="offline"))
            await session.commit()

    run(seed())
    try:
        with TestClient(app, base_url=ORIGIN) as client:
            prefix = "/api/v1/presentation/entries"
            assert client.get(prefix).status_code == 401
            assert client.get("/api/v1/bridge/presentation/dispatches").status_code == 401
            assert _login(client, "buyer@example.com", BUYER_PASSWORD).status_code == 200
            assert client.get(prefix).json()["items"] == []
            body = {"requestId": str(uuid4()), "estimateId": str(uuid4()), "expectedVersion": 1}
            assert client.post(prefix, json=body, headers={"Origin": ORIGIN}).status_code == 403
            headers = {"Origin": ORIGIN, "X-CSRF-Token": client.cookies.get("xxx_csrf")}
            assert client.post(prefix, json=body, headers=headers).status_code == 404
            assert (
                client.post(prefix, json={**body, "paid": True}, headers=headers).status_code == 422
            )
            assert (
                client.post(
                    f"{prefix}/{uuid4()}/admit", json={"expectedVersion": 1}, headers=headers
                ).status_code
                == 403
            )
            client.cookies.clear()
            assert _login(client, "owner@example.com", OWNER_PASSWORD).status_code == 200
            headers = {"Origin": ORIGIN, "X-CSRF-Token": client.cookies.get("xxx_csrf")}
            assert (
                client.post(
                    f"{prefix}/{uuid4()}/clearance",
                    json=readiness(1).model_dump(by_alias=True),
                    headers=headers,
                ).status_code
                == 403
            )
            app.state.settings.presentation_mode = False
            assert client.get(prefix).status_code == 404
    finally:
        run(engine.dispose())
