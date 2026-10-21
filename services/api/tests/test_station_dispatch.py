"""Owner-authorized commerce dispatch; all identities and artifacts are fictional."""

from asyncio import run
from contextlib import asynccontextmanager
from datetime import timedelta
from functools import wraps
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from test_commerce import seed_commerce
from test_workflow_safety import paid_job

from xxx_api.models.analysis import AnalysisRun
from xxx_api.models.commerce import PaymentIntent, PrintAuthorization, PrintJobEvent
from xxx_api.models.quotes import QuoteRequest
from xxx_api.services import bridge as service
from xxx_api.services.commerce import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    complete_readiness,
    transition_job,
    utc,
)


def run_case(function):
    @wraps(function)
    def execute(*args, **kwargs):
        return run(function(*args, **kwargs))

    return execute


@asynccontextmanager
async def dispatch_case(
    *, quantity=1, adapter="station-zmod-v1", database_url="sqlite+aiosqlite:///:memory:"
):
    engine, sessions, owner, buyer, request, estimate = await seed_commerce(database_url)
    try:
        async with sessions() as session:
            row = await session.get(QuoteRequest, request.id)
            row.quantity = quantity
            row.print_specification = {
                "presetCode": "lab-pla",
                "presetLabel": "LAB ONLY PLA",
                "materialCode": "lab-pla",
                "profileSha256": "b" * 64,
                "colour": "red",
                "settings": {
                    "filamentType": "PLA",
                    "nozzleDiameterMm": "0.4",
                    "layerHeightMm": "0.2",
                    "infillPercent": 20,
                    "supports": False,
                    "wallLoops": 2,
                },
            }
            analysis = await session.scalar(select(AnalysisRun))
            analysis.print_preset_code = "lab-pla"
            await session.commit()
            job = await paid_job(session, owner, buyer, row, estimate)
            installation, token = await service.begin_pairing(session, owner, "Fictional station")
            installation, _credential = await service.finish_pairing(
                session, token, adapter=adapter
            )
            installation.last_heartbeat_at = utc()
            await session.commit()
            job = await transition_job(
                session, owner=owner, job_id=job.id, expected_version=job.version, action="prepare"
            )
            job = await complete_readiness(
                session,
                owner=owner,
                job_id=job.id,
                expected_version=job.version,
                checklist=dict.fromkeys(
                    [
                        "bedClear",
                        "materialLoaded",
                        "nozzleChecked",
                        "areaClear",
                        "artifactReviewed",
                    ],
                    True,
                ),
            )
            yield session, owner, buyer, job, installation
    finally:
        await engine.dispose()


def event(state, *, sequence=None, **changes):
    return {
        "sourceEventId": sequence or f"test:{state}",
        "state": state,
        "observedAt": utc().isoformat(),
        "printerFilename": f"pf_{'a' * 32}_{'c' * 12}.gcode",
        "dispatchSha256": "d" * 64,
        "progressBps": 5000 if state == "printing" else None,
        "refusalCode": None,
        **changes,
    }


@run_case
async def test_dispatch_is_single_claim_and_telemetry_moves_only_exact_job_to_qa():
    async with dispatch_case() as (session, owner, _buyer, job, bridge):
        authorization = await service.authorize_dispatch(
            session, owner, job.id, job.version, enabled=True
        )
        assert job.status == "authorized"
        first = await service.claim_dispatch(session, bridge, authorization.id, enabled=True)
        assert first == await service.claim_dispatch(
            session, bridge, authorization.id, enabled=True
        )
        assert first["artifactSha256"] == "c" * 64
        assert "buyer" not in str(first).lower()
        sent = event("sent")
        await service.record_dispatch_event(session, bridge, authorization.id, sent, enabled=True)
        await service.record_dispatch_event(session, bridge, authorization.id, sent, enabled=True)
        assert (
            await session.scalar(
                select(func.count())
                .select_from(PrintJobEvent)
                .where(PrintJobEvent.event_type == "plate_sent")
            )
            == 1
        )
        await service.record_dispatch_event(
            session, bridge, authorization.id, event("printing"), enabled=True
        )
        assert job.status == "printing"
        await service.record_dispatch_event(
            session, bridge, authorization.id, event("completed"), enabled=True
        )
        assert job.status == "qa"
        with pytest.raises(WorkflowConflictError):
            await service.record_dispatch_event(
                session, bridge, authorization.id, event("printing", sequence="later"), enabled=True
            )


@run_case
@pytest.mark.parametrize(
    "quantity,adapter,enabled",
    [
        (2, "station-zmod-v1", True),
        (1, "manual-orca", True),
        (1, "station-zmod-v1", False),
    ],
)
async def test_dispatch_rejects_unsupported_quantity_manual_adapter_or_disabled_switch(
    quantity,
    adapter,
    enabled,
):
    async with dispatch_case(quantity=quantity, adapter=adapter) as (
        session,
        owner,
        _,
        job,
        _bridge,
    ):
        with pytest.raises(WorkflowConflictError):
            await service.authorize_dispatch(session, owner, job.id, job.version, enabled=enabled)
        assert await session.scalar(select(func.count()).select_from(PrintAuthorization)) == 0


@run_case
async def test_dispatch_cannot_bypass_captured_payment_or_owner_role():
    async with dispatch_case() as (session, owner, buyer, job, _bridge):
        with pytest.raises(WorkflowNotFoundError):
            await service.authorize_dispatch(session, buyer, job.id, job.version, enabled=True)
        intent = await session.scalar(select(PaymentIntent))
        intent.status = "authorized"
        await session.commit()
        with pytest.raises(WorkflowConflictError):
            await service.authorize_dispatch(session, owner, job.id, job.version, enabled=True)


@run_case
async def test_dispatch_rejects_expired_and_duplicate_authorization():
    async with dispatch_case() as (session, owner, _, job, bridge):
        version = job.version
        authorization = await service.authorize_dispatch(
            session, owner, job.id, version, enabled=True
        )
        with pytest.raises(WorkflowConflictError):
            await service.authorize_dispatch(session, owner, job.id, version, enabled=True)
        authorization.expires_at = utc() - timedelta(seconds=1)
        await session.commit()
        with pytest.raises(WorkflowNotFoundError):
            await service.claim_dispatch(session, bridge, authorization.id, enabled=True)


@run_case
async def test_dispatch_rejects_completion_before_send_wrong_hash_and_changed_replay():
    async with dispatch_case() as (session, owner, _, job, bridge):
        authorization = await service.authorize_dispatch(
            session, owner, job.id, job.version, enabled=True
        )
        await service.claim_dispatch(session, bridge, authorization.id, enabled=True)
        with pytest.raises(WorkflowConflictError):
            await service.record_dispatch_event(
                session, bridge, authorization.id, event("completed"), enabled=True
            )
        sent = event("sent")
        await service.record_dispatch_event(session, bridge, authorization.id, sent, enabled=True)
        with pytest.raises(WorkflowConflictError):
            await service.record_dispatch_event(
                session,
                bridge,
                authorization.id,
                {**sent, "dispatchSha256": "e" * 64},
                enabled=True,
            )
        for changed in [
            {"dispatchSha256": "e" * 64},
            {"printerFilename": f"pf_{'b' * 32}_{'c' * 12}.gcode"},
        ]:
            with pytest.raises(WorkflowConflictError):
                await service.record_dispatch_event(
                    session, bridge, authorization.id, event("printing", **changed), enabled=True
                )


def test_dispatch_http_rejects_buyers_and_unenrolled_owner():
    from asyncio import run

    from fastapi.testclient import TestClient
    from test_owner_auth_http import BUYER_PASSWORD, ORIGIN, OWNER_PASSWORD, _build_app, _login

    app, engine, _sessions, _limiter = _build_app()
    with TestClient(app, base_url=ORIGIN) as client:
        _login(client, "buyer@example.com", BUYER_PASSWORD)
        route = f"/api/v1/owner/production/{uuid4()}/dispatch"
        assert client.get(route).status_code == 403
        assert client.post(route, json={"expectedVersion": 1}).status_code == 403
        assert client.get("/api/v1/bridge/dispatches").status_code == 401
        client.cookies.clear()
        _login(client, "owner@example.com", OWNER_PASSWORD)
        assert (
            client.post(
                route,
                json={"expectedVersion": 1},
                headers={
                    "Origin": ORIGIN,
                    "X-CSRF-Token": client.cookies.get("xxx_csrf"),
                },
            ).status_code
            == 403
        )
    run(engine.dispose())


def test_dispatch_http_requires_recent_mfa_trusted_origin_and_csrf():
    import pyotp
    from fastapi.testclient import TestClient
    from test_owner_auth_http import ORIGIN, OWNER_PASSWORD, _build_app, _login

    app, engine, _sessions, _limiter = _build_app()
    app.state.settings.printer_dispatch_enabled = True
    with TestClient(app, base_url=ORIGIN) as client:
        _login(client, "owner@example.com", OWNER_PASSWORD)
        headers = {"Origin": ORIGIN, "X-CSRF-Token": client.cookies.get("xxx_csrf")}
        enrollment = client.post(
            "/api/v1/auth/mfa/totp/enroll",
            headers=headers,
            json={"currentPassword": OWNER_PASSWORD},
        )
        assert enrollment.status_code == 200
        confirmed = client.post(
            "/api/v1/auth/mfa/totp/confirm",
            headers=headers,
            json={"code": pyotp.TOTP(enrollment.json()["secret"]).now()},
        )
        assert confirmed.status_code == 200
        route = f"/api/v1/owner/production/{uuid4()}/dispatch"
        assert (
            client.post(route, json={"expectedVersion": 1}, headers={"Origin": ORIGIN}).status_code
            == 403
        )
        assert (
            client.post(
                route,
                json={"expectedVersion": 1},
                headers={"X-CSRF-Token": headers["X-CSRF-Token"]},
            ).status_code
            == 403
        )
        assert (
            client.post(
                route,
                json={"expectedVersion": 1},
                headers={**headers, "Origin": "https://untrusted.example"},
            ).status_code
            == 403
        )
        assert client.post(route, json={"expectedVersion": 1}, headers=headers).status_code == 404
        assert (
            client.post(
                route, json={"expectedVersion": 1, "printerCommand": "START"}, headers=headers
            ).status_code
            == 422
        )
    run(engine.dispose())


@run_case
async def test_expired_authorization_requires_new_readiness_and_keeps_reservation():
    from xxx_api.models.commerce import Printer

    async with dispatch_case() as (session, owner, _, job, _bridge):
        grant = await service.authorize_dispatch(session, owner, job.id, job.version, enabled=True)
        grant.expires_at = utc() - timedelta(seconds=1)
        await session.commit()
        with pytest.raises(WorkflowConflictError, match="authorization_reset"):
            await service.authorize_dispatch(session, owner, job.id, job.version, enabled=True)
        await session.refresh(grant)
        assert job.status == "preparing" and grant.revoked_at is not None
        assert (await session.scalar(select(Printer))).active_job_id == job.id
        with pytest.raises(WorkflowConflictError):
            await service.authorize_dispatch(session, owner, job.id, job.version, enabled=True)


@run_case
async def test_revoked_bridge_other_bridge_and_tampered_manifest_cannot_claim():
    from xxx_api.models.commerce import BridgeInstallation, PrintJobItem

    async with dispatch_case() as (session, owner, _, job, bridge):
        grant = await service.authorize_dispatch(session, owner, job.id, job.version, enabled=True)
        stranger = BridgeInstallation(id=uuid4(), adapter_name=service.STATION_ADAPTER)
        with pytest.raises(WorkflowNotFoundError):
            await service.claim_dispatch(session, stranger, grant.id, enabled=True)
        item = await session.scalar(select(PrintJobItem))
        original = item.artifact_sha256
        await session.execute(
            update(PrintJobItem).where(PrintJobItem.id == item.id).values(artifact_sha256="f" * 64)
        )
        await session.commit()
        with pytest.raises(WorkflowConflictError):
            await service.claim_dispatch(session, bridge, grant.id, enabled=True)
        await session.execute(
            update(PrintJobItem).where(PrintJobItem.id == item.id).values(artifact_sha256=original)
        )
        await session.commit()
        await service.revoke_bridge(session, owner, bridge.id)
        with pytest.raises(WorkflowNotFoundError):
            await service.claim_dispatch(session, bridge, grant.id, enabled=True)


@run_case
async def test_artifact_closes_after_send_and_owner_failure_blocks_late_completion():
    async with dispatch_case() as (session, owner, _, job, bridge):
        grant = await service.authorize_dispatch(session, owner, job.id, job.version, enabled=True)
        await service.claim_dispatch(session, bridge, grant.id, enabled=True)
        await service.dispatch_artifact_access(session, bridge, grant.id, enabled=True)
        await service.record_dispatch_event(session, bridge, grant.id, event("sent"), enabled=True)
        with pytest.raises(WorkflowConflictError):
            await service.dispatch_artifact_access(session, bridge, grant.id, enabled=True)
        await transition_job(
            session,
            owner=owner,
            job_id=job.id,
            expected_version=job.version,
            action="print_failed",
            note="Inspected simulated failed attempt",
        )
        with pytest.raises(WorkflowConflictError):
            await service.record_dispatch_event(
                session, bridge, grant.id, event("completed"), enabled=True
            )


@run_case
async def test_refusal_keeps_reservation_but_requires_fresh_readiness():
    async with dispatch_case() as (session, owner, _, job, bridge):
        grant = await service.authorize_dispatch(session, owner, job.id, job.version, enabled=True)
        await service.claim_dispatch(session, bridge, grant.id, enabled=True)
        await service.record_dispatch_event(
            session,
            bridge,
            grant.id,
            event("refused", printerFilename=None, dispatchSha256=None, refusalCode="wrong_spool"),
            enabled=True,
        )
        assert job.status == "preparing"
        with pytest.raises(WorkflowConflictError):
            await service.authorize_dispatch(session, owner, job.id, job.version, enabled=True)
        await complete_readiness(
            session,
            owner=owner,
            job_id=job.id,
            expected_version=job.version,
            checklist=dict.fromkeys(
                ["bedClear", "materialLoaded", "nozzleChecked", "areaClear", "artifactReviewed"],
                True,
            ),
        )
        second = await service.authorize_dispatch(session, owner, job.id, job.version, enabled=True)
        assert second.id != grant.id


@run_case
async def test_disabled_switch_blocks_new_send_but_accepts_inflight_completion():
    async with dispatch_case() as (session, owner, _, job, bridge):
        grant = await service.authorize_dispatch(session, owner, job.id, job.version, enabled=True)
        await service.claim_dispatch(session, bridge, grant.id, enabled=True)
        with pytest.raises(WorkflowConflictError):
            await service.record_dispatch_event(
                session, bridge, grant.id, event("sent"), enabled=False
            )
        await service.record_dispatch_event(session, bridge, grant.id, event("sent"), enabled=True)
        await service.record_dispatch_event(
            session, bridge, grant.id, event("completed"), enabled=False
        )
        assert job.status == "qa"


@run_case
async def test_claim_does_not_extend_physical_readiness_deadline():
    from xxx_api.models.commerce import PrintReadinessCheck

    async with dispatch_case() as (session, owner, _, job, bridge):
        grant = await service.authorize_dispatch(session, owner, job.id, job.version, enabled=True)
        await service.claim_dispatch(session, bridge, grant.id, enabled=True)
        await session.execute(
            update(PrintReadinessCheck)
            .where(PrintReadinessCheck.id == grant.readiness_check_id)
            .values(completed_at=utc() - timedelta(minutes=11))
        )
        await session.commit()
        with pytest.raises(WorkflowConflictError):
            await service.record_dispatch_event(
                session, bridge, grant.id, event("sent"), enabled=True
            )


@run_case
@pytest.mark.parametrize("revoked,enabled", [(True, True), (True, False), (False, False)])
async def test_unclaimed_revoked_or_expired_grant_can_recover_without_enabling_sends(
    revoked, enabled
):
    async with dispatch_case() as (session, owner, _, job, bridge):
        grant = await service.authorize_dispatch(session, owner, job.id, job.version, enabled=True)
        if revoked:
            await service.revoke_bridge(session, owner, bridge.id)
        else:
            grant.expires_at = utc() - timedelta(seconds=1)
            await session.commit()
        with pytest.raises(WorkflowConflictError):
            await service.authorize_dispatch(session, owner, job.id, job.version, enabled=enabled)
        assert job.status == "preparing", (
            "An unclaimed revoked/expired send must not trap the printer reservation."
        )


@run_case
async def test_claimed_revoked_grant_never_resets_and_requires_noted_owner_failure():
    async with dispatch_case() as (session, owner, _, job, bridge):
        grant = await service.authorize_dispatch(session, owner, job.id, job.version, enabled=True)
        await service.claim_dispatch(session, bridge, grant.id, enabled=True)
        await service.revoke_bridge(session, owner, bridge.id)
        with pytest.raises(WorkflowConflictError):
            await service.authorize_dispatch(session, owner, job.id, job.version, enabled=False)
        assert job.status == "claimed"
        with pytest.raises(WorkflowConflictError):
            await transition_job(
                session,
                owner=owner,
                job_id=job.id,
                expected_version=job.version,
                action="print_failed",
                note="",
            )
        await transition_job(
            session,
            owner=owner,
            job_id=job.id,
            expected_version=job.version,
            action="print_failed",
            note="Inspected the fictional local attempt",
        )
        assert job.status == "failed"


@run_case
async def test_reset_requires_fresh_readiness_before_manual_fallback_and_is_not_repeated():
    async with dispatch_case() as (session, owner, _, job, bridge):
        await service.authorize_dispatch(session, owner, job.id, job.version, enabled=True)
        await service.revoke_bridge(session, owner, bridge.id)
        with pytest.raises(WorkflowConflictError, match="authorization_reset_readiness_required"):
            await service.authorize_dispatch(session, owner, job.id, job.version, enabled=False)
        with pytest.raises(WorkflowConflictError, match="disabled"):
            await service.authorize_dispatch(session, owner, job.id, job.version, enabled=False)
        with pytest.raises(WorkflowConflictError):
            await transition_job(
                session,
                owner=owner,
                job_id=job.id,
                expected_version=job.version,
                action="manual_started",
            )
        await complete_readiness(
            session,
            owner=owner,
            job_id=job.id,
            expected_version=job.version,
            checklist=dict.fromkeys(
                ["bedClear", "materialLoaded", "nozzleChecked", "areaClear", "artifactReviewed"],
                True,
            ),
        )
        await transition_job(
            session,
            owner=owner,
            job_id=job.id,
            expected_version=job.version,
            action="manual_started",
        )
        assert job.status == "printing"


@run_case
@pytest.mark.parametrize("trial", range(4))
async def test_claim_and_expiry_reset_have_exactly_one_transactional_winner(
    tmp_path, monkeypatch, trial
):
    import asyncio
    from contextvars import ContextVar

    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy.sql.dml import Update

    from xxx_api.models.commerce import PrintJob

    async with dispatch_case(
        database_url=f"sqlite+aiosqlite:///{tmp_path / f'race-{trial}.db'}"
    ) as (session, owner, _, job, bridge):
        grant = await service.authorize_dispatch(session, owner, job.id, job.version, enabled=True)
        base = utc()
        grant.expires_at = base + timedelta(seconds=60)
        await session.commit()
        sessions = async_sessionmaker(session.bind, expire_on_commit=False, autoflush=False)
        clock = ContextVar("dispatch_race_clock", default=base)
        original_utc = service.utc
        monkeypatch.setattr(
            service,
            "utc",
            lambda value=None: original_utc(value) if value is not None else clock.get(),
        )
        barrier = asyncio.Barrier(2)

        async def compete(claiming):
            clock.set(base if claiming else base + timedelta(seconds=120))
            async with sessions() as contender:
                original_scalar = contender.scalar

                async def synchronized(statement, *args, **kwargs):
                    if (
                        isinstance(statement, Update)
                        and statement.table.name == "print_authorizations"
                    ):
                        await barrier.wait()
                    return await original_scalar(statement, *args, **kwargs)

                contender.scalar = synchronized
                try:
                    if claiming:
                        await service.claim_dispatch(contender, bridge, grant.id, enabled=True)
                        return "claim"
                    await service.authorize_dispatch(
                        contender, owner, job.id, job.version, enabled=False
                    )
                except (WorkflowConflictError, WorkflowNotFoundError) as error:
                    return (
                        "reset"
                        if str(error).startswith("authorization_reset_readiness_required")
                        else "lost"
                    )

        results = await asyncio.wait_for(asyncio.gather(compete(True), compete(False)), timeout=10)
        assert sum(result in {"claim", "reset"} for result in results) == 1
        async with sessions() as check:
            actual = await check.get(PrintJob, job.id)
            authorization = await check.get(PrintAuthorization, grant.id)
            if "claim" in results:
                assert actual.status == "claimed" and authorization.claimed_at is not None
                assert authorization.revoked_at is None
            else:
                assert actual.status == "preparing" and authorization.claimed_at is None
                assert authorization.revoked_at is not None
