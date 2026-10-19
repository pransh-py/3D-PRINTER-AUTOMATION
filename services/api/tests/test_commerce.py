"""Quotation, payment and production invariants in disposable databases."""

from asyncio import run
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from xxx_api.domain.auth import UserStatus
from xxx_api.domain.quotes import (
    AnalysisAssetStatus,
    AnalysisRunStatus,
    ModelAssetStatus,
    ModelFormat,
    QuoteRequestStatus,
)
from xxx_api.domain.roles import Role
from xxx_api.models import Base, User
from xxx_api.models.analysis import AnalysisAssetResult, AnalysisRun, OutboxEvent
from xxx_api.models.commerce import Order, PaymentIntent, PaymentProviderEvent, PrintJob
from xxx_api.models.quotes import ModelAsset, QuoteRequest
from xxx_api.services.commerce import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    accept_quote,
    complete_readiness,
    enqueue_paid_orders,
    get_order,
    issue_quote,
    record_captured_payment,
    transition_job,
    update_fulfillment,
)
from xxx_api.services.pricing import (
    PricingConflictError,
    activate_pricing_policy,
    create_pricing_policy,
    create_quote_estimate,
)


def test_commerce_api_is_authenticated_and_does_not_offer_self_payment_confirmation():
    from fastapi.testclient import TestClient

    from xxx_api.config import Settings
    from xxx_api.main import create_app

    app = create_app(Settings(environment="test"))
    with TestClient(app) as client:
        assert client.get("/api/v1/orders").status_code == 401
        assert client.post("/api/v1/orders/confirm-payment", json={}).status_code == 405


def test_fulfillment_requires_qa_and_actual_delivery():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(UTC)
        owner = User(
            id=uuid4(),
            email="owner@lab.example",
            display_name="Lab owner",
            password_hash="unused",
            role=Role.OWNER,
            owner_slot="primary",
            status=UserStatus.ACTIVE,
            password_changed_at=now,
            email_verified_at=now,
        )
        buyer = User(
            id=uuid4(),
            email="buyer@lab.example",
            display_name="Lab buyer",
            password_hash="unused",
            role=Role.BUYER,
            status=UserStatus.ACTIVE,
            password_changed_at=now,
            email_verified_at=now,
        )
        order = Order(
            id=uuid4(),
            buyer_id=buyer.id,
            accepted_quote_id=uuid4(),
            public_reference="PF-LAB",
            status="payment_pending",
            version=1,
            currency="INR",
            amount_paise=11800,
            commercial_snapshot={},
            accepted_at=now,
        )
        async with sessions() as session:
            session.add_all([owner, buyer, order])
            await session.commit()
            with pytest.raises(WorkflowConflictError):
                await update_fulfillment(
                    session,
                    owner=owner,
                    order_id=order.id,
                    expected_version=1,
                    status="ready_for_pickup",
                )
        await engine.dispose()

    run(scenario())


async def seed_commerce(database_url="sqlite+aiosqlite:///:memory:"):
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    now = datetime.now(UTC)
    owner = User(
        id=uuid4(),
        email="owner@lab.example",
        display_name="Lab owner",
        password_hash="unused",
        role=Role.OWNER,
        owner_slot="primary",
        status=UserStatus.ACTIVE,
        password_changed_at=now,
        email_verified_at=now,
    )
    buyer = User(
        id=uuid4(),
        email="buyer@lab.example",
        display_name="Lab buyer",
        password_hash="unused",
        role=Role.BUYER,
        status=UserStatus.ACTIVE,
        password_changed_at=now,
        email_verified_at=now,
    )
    request = QuoteRequest(
        id=uuid4(),
        buyer_id=buyer.id,
        client_token=uuid4(),
        status=QuoteRequestStatus.ANALYSIS_READY,
        version=3,
        quantity=1,
        fulfillment_mode="pickup",
        assets=[],
        analysis_runs=[],
        estimates=[],
    )
    asset = ModelAsset(
        id=uuid4(),
        quote_request_id=request.id,
        client_token=uuid4(),
        original_filename="lab.stl",
        declared_format=ModelFormat.STL,
        declared_content_type="application/octet-stream",
        expected_size_bytes=100,
        actual_size_bytes=100,
        claimed_sha256="a" * 64,
        verified_sha256="a" * 64,
        storage_key="lab/source",
        status=ModelAssetStatus.VALIDATED,
        upload_expires_at=now,
        uploaded_at=now,
    )
    analysis = AnalysisRun(
        id=uuid4(),
        quote_request_id=request.id,
        request_version=2,
        status=AnalysisRunStatus.SUCCEEDED,
        attempt_count=1,
        validator_version="test",
        slicer_name="fixture",
        slicer_version="1",
        profile_sha256="b" * 64,
        material_code="lab-pla",
        queued_at=now,
        completed_at=now,
        asset_results=[],
    )
    result = AnalysisAssetResult(
        id=uuid4(),
        analysis_run_id=analysis.id,
        model_asset_id=asset.id,
        status=AnalysisAssetStatus.SLICED,
        detected_format=ModelFormat.STL,
        verified_sha256="a" * 64,
        filament_mg=12500,
        duration_seconds=1800,
        artifact_storage_key="lab/approved.gcode",
        artifact_sha256="c" * 64,
        warning_codes=[],
    )
    request.assets = [asset]
    request.analysis_runs = [analysis]
    analysis.asset_results = [result]
    async with sessions() as session:
        session.add_all([owner, buyer, request, asset, analysis, result])
        await session.commit()
        policy = await create_pricing_policy(
            session,
            owner=owner,
            machine_rate_paise_per_hour=10000,
            setup_fee_paise=1000,
            minimum_order_paise=10000,
            contingency_bps=1000,
            tax_bps=1800,
            estimate_validity_hours=24,
            materials=[("lab-pla", "LAB ONLY PLA", 200)],
        )
        await activate_pricing_policy(session, owner=owner, policy_id=policy.id)
        estimate = await create_quote_estimate(
            session,
            owner=owner,
            quote_request_id=request.id,
            client_token=uuid4(),
            expected_quote_version=3,
            analysis_run_id=analysis.id,
            material_code="lab-pla",
        )
    return engine, sessions, owner, buyer, request, estimate


def test_quote_acceptance_is_owned_idempotent_and_snapshot_is_fixed():
    async def scenario():
        engine, sessions, owner, buyer, request, estimate = await seed_commerce()
        async with sessions() as session:
            quotation = await issue_quote(
                session,
                owner=owner,
                request_id=request.id,
                estimate_id=estimate.id,
                expected_version=4,
                expires_at=datetime.now(UTC) + timedelta(hours=3),
            )
            stranger = User(id=uuid4(), role=Role.BUYER)
            with pytest.raises(WorkflowNotFoundError):
                await accept_quote(session, buyer=stranger, quote_id=quotation.id)
            order = await accept_quote(session, buyer=buyer, quote_id=quotation.id)
            again = await accept_quote(session, buyer=buyer, quote_id=quotation.id)
            assert again.id == order.id
            assert order.amount_paise == 11800
            assert order.commercial_snapshot["profileSha256"] == "b" * 64
            assert await session.scalar(select(func.count()).select_from(Order)) == 1
            with pytest.raises(WorkflowNotFoundError):
                await get_order(session, user=stranger, order_id=order.id)
            with pytest.raises(WorkflowConflictError):
                await issue_quote(
                    session,
                    owner=owner,
                    request_id=request.id,
                    estimate_id=estimate.id,
                    expected_version=5,
                    expires_at=datetime.now(UTC) + timedelta(hours=3),
                )
        await engine.dispose()

    run(scenario())


def test_expired_estimate_refresh_supersedes_unaccepted_quote_and_locks_accepted_price():
    async def scenario():
        engine, sessions, owner, buyer, request, estimate = await seed_commerce()
        async with sessions() as session:
            quotation = await issue_quote(
                session,
                owner=owner,
                request_id=request.id,
                estimate_id=estimate.id,
                expected_version=4,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            refreshed = await create_quote_estimate(
                session,
                owner=owner,
                quote_request_id=request.id,
                client_token=uuid4(),
                expected_quote_version=5,
                analysis_run_id=estimate.analysis_run_id,
                material_code="lab-pla",
                now=datetime.now(UTC) + timedelta(days=2),
            )
            assert refreshed.id != estimate.id
            assert refreshed.quote_request_version == 6
            await session.refresh(quotation)
            assert quotation.status == "superseded"
            assert quotation.total_paise == estimate.total_paise
            with pytest.raises(WorkflowConflictError, match="current, unexpired"):
                await accept_quote(session, buyer=buyer, quote_id=quotation.id)
            new_quote = await issue_quote(
                session,
                owner=owner,
                request_id=request.id,
                estimate_id=refreshed.id,
                expected_version=6,
                expires_at=datetime.now(UTC) + timedelta(hours=3),
            )
            accepted = await accept_quote(session, buyer=buyer, quote_id=new_quote.id)
            accepted_id, expected_amount = accepted.id, estimate.total_paise
            with pytest.raises(PricingConflictError, match="accepted"):
                await create_quote_estimate(
                    session,
                    owner=owner,
                    quote_request_id=request.id,
                    client_token=uuid4(),
                    expected_quote_version=8,
                    analysis_run_id=estimate.analysis_run_id,
                    material_code="lab-pla",
                )
            persisted = await session.get(Order, accepted_id)
            assert persisted.amount_paise == expected_amount
        await engine.dispose()

    run(scenario())


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount_paise", 1),
        ("currency", "USD"),
        ("captured", False),
        ("provider_order_id", "order_wrong"),
    ],
)
def test_payment_mismatch_never_queues(field, value):
    async def scenario():
        engine, sessions, owner, buyer, request, estimate = await seed_commerce()
        async with sessions() as session:
            quote = await issue_quote(
                session,
                owner=owner,
                request_id=request.id,
                estimate_id=estimate.id,
                expected_version=4,
                expires_at=datetime.now(UTC) + timedelta(hours=3),
            )
            order = await accept_quote(session, buyer=buyer, quote_id=quote.id)
            intent, event = await seed_payment(session, order)
            payload = dict(
                event_id=event.id,
                intent_id=intent.id,
                provider_order_id="order_lab",
                provider_payment_id="pay_lab",
                amount_paise=11800,
                currency="INR",
                captured=True,
            )
            payload[field] = value
            with pytest.raises(WorkflowConflictError):
                await record_captured_payment(session, **payload)
            assert await session.scalar(select(func.count()).select_from(PrintJob)) == 0
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .where(OutboxEvent.topic == "production.requested")
                )
                == 0
            )
        await engine.dispose()

    run(scenario())


async def seed_payment(session, order):
    now = datetime.now(UTC)
    intent = PaymentIntent(
        id=uuid4(),
        order_id=order.id,
        version=1,
        provider="razorpay",
        status="checkout_pending",
        currency="INR",
        amount_paise=order.amount_paise,
        payment_reference=f"lab-{uuid4()}",
        provider_order_id="order_lab",
    )
    event = PaymentProviderEvent(
        id=uuid4(),
        provider="razorpay",
        provider_event_id="evt_lab",
        event_type="payment.captured",
        payload_sha256="d" * 64,
        signature_validated_at=now,
        status="received",
        received_at=now,
    )
    session.add_all([intent, event])
    await session.commit()
    return intent, event


def test_payment_duplicate_print_readiness_and_pickup_lifecycle():
    async def scenario():
        engine, sessions, owner, buyer, request, estimate = await seed_commerce()
        async with sessions() as session:
            quote = await issue_quote(
                session,
                owner=owner,
                request_id=request.id,
                estimate_id=estimate.id,
                expected_version=4,
                expires_at=datetime.now(UTC) + timedelta(hours=3),
            )
            order = await accept_quote(session, buyer=buyer, quote_id=quote.id)
            intent, event = await seed_payment(session, order)
            kwargs = dict(
                event_id=event.id,
                intent_id=intent.id,
                provider_order_id="order_lab",
                provider_payment_id="pay_lab",
                amount_paise=11800,
                currency="INR",
                captured=True,
            )
            await record_captured_payment(session, **kwargs)
            await record_captured_payment(session, **kwargs)
            assert await enqueue_paid_orders(session) == 1
            assert await enqueue_paid_orders(session) == 0
            job = await session.scalar(select(PrintJob).where(PrintJob.order_id == order.id))
            assert job is not None
            with pytest.raises(WorkflowConflictError):
                await transition_job(
                    session, owner=owner, job_id=job.id, expected_version=1, action="manual_started"
                )
            job = await transition_job(
                session, owner=owner, job_id=job.id, expected_version=1, action="prepare"
            )
            with pytest.raises(WorkflowConflictError):
                await complete_readiness(
                    session,
                    owner=owner,
                    job_id=job.id,
                    expected_version=job.version,
                    checklist={"bedClear": True},
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
            job = await complete_readiness(
                session, owner=owner, job_id=job.id, expected_version=job.version, checklist=checks
            )
            for action in ("manual_started", "print_completed", "qa_pass"):
                job = await transition_job(
                    session, owner=owner, job_id=job.id, expected_version=job.version, action=action
                )
            order = await session.get(Order, order.id)
            fulfillment = await update_fulfillment(
                session,
                owner=owner,
                order_id=order.id,
                expected_version=order.version,
                status="ready_for_pickup",
            )
            assert fulfillment.status == "ready_for_pickup"
            assert order.status != "completed"
            await update_fulfillment(
                session,
                owner=owner,
                order_id=order.id,
                expected_version=order.version,
                status="completed",
            )
            assert order.status == "completed"
            assert await session.scalar(select(func.count()).select_from(PrintJob)) == 1
        await engine.dispose()

    run(scenario())
