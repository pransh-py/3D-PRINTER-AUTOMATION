"""Adversarial commercial, bridge and migration checks in isolated lab state."""

from asyncio import gather, run
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select
from test_commerce import seed_commerce, seed_payment

from xxx_api.models.commerce import Order, Printer, PrintJob, Quote
from xxx_api.services.bridge import (
    authenticate_bridge,
    authorize_handoff,
    begin_pairing,
    finish_pairing,
    handoff_access,
    revoke_bridge,
)
from xxx_api.services.commerce import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    accept_quote,
    complete_readiness,
    enqueue_paid_orders,
    issue_quote,
    record_captured_payment,
    transition_job,
)
from xxx_api.services.pricing import PricingConflictError, create_quote_estimate


async def paid_job(session, owner, buyer, request, estimate):
    quote = await issue_quote(
        session,
        owner=owner,
        request_id=request.id,
        estimate_id=estimate.id,
        expected_version=request.version,
        expires_at=datetime.now(UTC) + timedelta(hours=2),
    )
    order = await accept_quote(session, buyer=buyer, quote_id=quote.id)
    intent, event = await seed_payment(session, order)
    await record_captured_payment(
        session,
        event_id=event.id,
        intent_id=intent.id,
        provider_order_id="order_lab",
        provider_payment_id="pay_lab",
        amount_paise=order.amount_paise,
        currency="INR",
        captured=True,
    )
    await enqueue_paid_orders(session)
    return await session.scalar(select(PrintJob).where(PrintJob.order_id == order.id))


def test_stale_versions_and_immutable_commercial_evidence():
    async def scenario():
        engine, sessions, owner, buyer, request, estimate = await seed_commerce()
        async with sessions() as session:
            with pytest.raises(WorkflowConflictError, match="changed"):
                await issue_quote(
                    session,
                    owner=owner,
                    request_id=request.id,
                    estimate_id=estimate.id,
                    expected_version=1,
                    expires_at=datetime.now(UTC) + timedelta(hours=2),
                )
            quote = await issue_quote(
                session,
                owner=owner,
                request_id=request.id,
                estimate_id=estimate.id,
                expected_version=4,
                expires_at=datetime.now(UTC) + timedelta(hours=2),
            )
            order = await accept_quote(session, buyer=buyer, quote_id=quote.id)
            quote_id = quote.id
            order.amount_paise += 1
            with pytest.raises(ValueError, match="immutable"):
                await session.flush()
            await session.rollback()
            stored = await session.get(Quote, quote_id)
            stored.total_paise += 1
            with pytest.raises(ValueError, match="immutable"):
                await session.flush()
            await session.rollback()
        await engine.dispose()

    run(scenario())


def test_expired_and_superseded_quotes_cannot_be_accepted():
    async def scenario():
        engine, sessions, owner, buyer, request, estimate = await seed_commerce()
        async with sessions() as session:
            first = await issue_quote(
                session,
                owner=owner,
                request_id=request.id,
                estimate_id=estimate.id,
                expected_version=4,
                expires_at=datetime.now(UTC) + timedelta(hours=2),
            )
            second = await issue_quote(
                session,
                owner=owner,
                request_id=request.id,
                estimate_id=estimate.id,
                expected_version=5,
                expires_at=datetime.now(UTC) + timedelta(hours=2),
                adjustment_paise=-100,
                reason="LAB ONLY adjustment",
            )
            with pytest.raises(WorkflowConflictError):
                await accept_quote(session, buyer=buyer, quote_id=first.id)
            with pytest.raises(WorkflowConflictError):
                await accept_quote(
                    session,
                    buyer=buyer,
                    quote_id=second.id,
                    now=datetime.now(UTC) + timedelta(days=1),
                )
        await engine.dispose()

    run(scenario())


def test_pairing_is_single_use_and_revocation_blocks_exact_manifest_handoff():
    async def scenario():
        engine, sessions, owner, buyer, request, estimate = await seed_commerce()
        async with sessions() as session:
            bridge, token = await begin_pairing(session, owner, "LAB ONLY Windows")
            bridge, credential = await finish_pairing(session, token)
            with pytest.raises(WorkflowNotFoundError):
                await finish_pairing(session, token)
            assert (await authenticate_bridge(session, credential)).id == bridge.id
            job = await paid_job(session, owner, buyer, request, estimate)
            await transition_job(
                session, owner=owner, job_id=job.id, expected_version=job.version, action="prepare"
            )
            checks = {
                key: True
                for key in (
                    "bedClear",
                    "materialLoaded",
                    "nozzleChecked",
                    "areaClear",
                    "artifactReviewed",
                )
            }
            await complete_readiness(
                session, owner=owner, job_id=job.id, expected_version=job.version, checklist=checks
            )
            with pytest.raises(WorkflowConflictError, match="online"):
                await authorize_handoff(session, owner, job.id, job.version)
            bridge.last_heartbeat_at = datetime.now(UTC)
            await session.commit()
            authorization = await authorize_handoff(session, owner, job.id, job.version)
            assert (await handoff_access(session, bridge, authorization.id))[1].id == job.id
            authorization.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
            with pytest.raises(WorkflowNotFoundError):
                await handoff_access(session, bridge, authorization.id)
            authorization.expires_at = datetime.now(UTC) + timedelta(minutes=1)
            await session.commit()
            await revoke_bridge(session, owner, bridge.id)
            with pytest.raises(WorkflowNotFoundError):
                await authenticate_bridge(session, credential)
            with pytest.raises(WorkflowNotFoundError):
                await handoff_access(session, bridge, authorization.id)
            printer = await session.scalar(select(Printer))
            assert printer.state == "unknown"  # No fabricated printer-idle observation.
        await engine.dispose()

    run(scenario())


def test_fresh_migrations_match_workflow_columns_and_constraints(tmp_path, monkeypatch):
    from xxx_api.config import get_settings

    # Reproduce a cached API configuration pointing elsewhere, without touching any real database.
    get_settings.cache_clear()
    monkeypatch.setenv("XXX_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'wrong-cached.db'}")
    get_settings()
    database = tmp_path / "isolated.db"
    url = f"sqlite+aiosqlite:///{database}"
    monkeypatch.setenv("XXX_DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    assert not (tmp_path / "wrong-cached.db").exists()

    async def inspect_schema():
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(url)
        async with engine.connect() as connection:

            def checks(sync):
                inspector = inspect(sync)
                assert {"preview_sha256", "preview_storage_key"} <= {
                    row["name"] for row in inspector.get_columns("analysis_asset_results")
                }
                assert {"ck_quote_requests_quantity", "ck_quote_requests_fulfillment"} <= {
                    row["name"] for row in inspector.get_check_constraints("quote_requests")
                }
                assert "ck_printers_single_code" in {
                    row["name"] for row in inspector.get_check_constraints("printers")
                }

            await connection.run_sync(checks)
        await engine.dispose()

    run(inspect_schema())
    with pytest.raises(RuntimeError, match="forward fix"):
        command.downgrade(config, "0005_versioned_pricing")
    get_settings.cache_clear()


def test_sqlite_utc_values_are_explicitly_zoned_without_changing_python_inputs():
    from xxx_api.schemas.quotes import AnalysisRunResponse

    value = AnalysisRunResponse(
        id=uuid4(),
        requestVersion=1,
        status="queued",
        attemptCount=0,
        validatorVersion="fixture",
        slicerName=None,
        slicerVersion=None,
        profileSha256=None,
        materialCode=None,
        queuedAt=datetime(2026, 10, 5, 1, 2, 3),
        startedAt=None,
        completedAt=None,
        failureCode=None,
        assets=[],
    )
    assert value.model_dump(mode="json", by_alias=True)["queuedAt"] == "2026-10-05T01:02:03+00:00"
    assert isinstance(value.model_dump()["queued_at"], datetime)


def test_fulfillment_response_maps_only_the_validated_accepted_address():
    from xxx_api.models.commerce import Fulfillment
    from xxx_api.schemas.commerce import FulfillmentOutput

    address = {
        "recipientName": "LAB ONLY",
        "phoneE164": "+919000000000",
        "line1": "Fictional test address",
        "line2": "",
        "locality": "Test",
        "district": "Test",
        "state": "Tamil Nadu",
        "postalCode": "600001",
        "countryCode": "IN",
    }
    row = Fulfillment(mode="shipping", status="pending", charge_paise=0, address_snapshot=address)
    output = FulfillmentOutput.model_validate(row).model_dump(mode="json", by_alias=True)
    assert output["destination"] == address
    assert "address_snapshot" not in output and "order_id" not in output


@pytest.mark.parametrize("recalculate", [False, True])
def test_acceptance_and_owner_price_changes_have_one_concurrent_winner(tmp_path, recalculate):
    async def scenario():
        engine, sessions, owner, buyer, request, estimate = await seed_commerce(
            f"sqlite+aiosqlite:///{tmp_path / 'concurrency.db'}"
        )
        async with sessions() as session:
            first = await issue_quote(
                session,
                owner=owner,
                request_id=request.id,
                estimate_id=estimate.id,
                expected_version=4,
                expires_at=datetime.now(UTC) + timedelta(hours=2),
            )
            first_id = first.id

        async def accept():
            async with sessions() as session:
                return await accept_quote(session, buyer=buyer, quote_id=first_id)

        async def reissue():
            async with sessions() as session:
                if recalculate:
                    return await create_quote_estimate(
                        session,
                        owner=owner,
                        quote_request_id=request.id,
                        client_token=uuid4(),
                        expected_quote_version=5,
                        analysis_run_id=estimate.analysis_run_id,
                        material_code="lab-pla",
                        now=datetime.now(UTC) + timedelta(days=2),
                    )
                return await issue_quote(
                    session,
                    owner=owner,
                    request_id=request.id,
                    estimate_id=estimate.id,
                    expected_version=5,
                    expires_at=datetime.now(UTC) + timedelta(hours=2),
                )

        results = await gather(accept(), reissue(), return_exceptions=True)
        assert sum(not isinstance(result, Exception) for result in results) == 1
        assert any(
            isinstance(result, (WorkflowConflictError, PricingConflictError)) for result in results
        )
        async with sessions() as session:
            orders = list(await session.scalars(select(Order)))
            issued = list(await session.scalars(select(Quote).where(Quote.status == "issued")))
            assert not (orders and issued)
        await engine.dispose()

    run(scenario())
