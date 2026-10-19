"""Deterministic pricing and immutable estimate invariants."""

from asyncio import run
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from xxx_api.domain.auth import UserStatus
from xxx_api.domain.pricing import (
    PricingInputs,
    PricingPolicyStatus,
    calculate_pricing_v1,
)
from xxx_api.domain.quotes import (
    AnalysisAssetStatus,
    AnalysisRunStatus,
    ModelAssetStatus,
    ModelFormat,
    QuoteRequestStatus,
)
from xxx_api.domain.roles import Role
from xxx_api.models import AnalysisAssetResult, AnalysisRun, Base, User
from xxx_api.models.pricing import PricingPolicy, QuoteEstimate
from xxx_api.models.quotes import ModelAsset, QuoteRequest
from xxx_api.services.pricing import (
    PricingConflictError,
    activate_pricing_policy,
    create_pricing_policy,
    create_quote_estimate,
)


def test_pricing_v1_rounds_components_up_and_applies_minimum_before_tax() -> None:
    breakdown = calculate_pricing_v1(
        PricingInputs(
            filament_mg=12_500,
            duration_seconds=1_800,
            material_rate_paise_per_gram=200,
            machine_rate_paise_per_hour=10_000,
            setup_fee_paise=1_000,
            contingency_bps=1_000,
            minimum_order_paise=10_000,
            tax_bps=1_800,
        )
    )
    assert breakdown.material_paise == 2_500
    assert breakdown.machine_paise == 5_000
    assert breakdown.setup_paise == 1_000
    assert breakdown.contingency_paise == 850
    assert breakdown.minimum_adjustment_paise == 650
    assert breakdown.pre_tax_paise == 10_000
    assert breakdown.tax_paise == 1_800
    assert breakdown.total_paise == 11_800


def test_pricing_v1_never_uses_fractional_paise_or_accepts_invalid_bps() -> None:
    one_paise = calculate_pricing_v1(
        PricingInputs(
            filament_mg=1,
            duration_seconds=1,
            material_rate_paise_per_gram=1,
            machine_rate_paise_per_hour=1,
            setup_fee_paise=0,
            contingency_bps=0,
            minimum_order_paise=0,
            tax_bps=0,
        )
    )
    assert one_paise.material_paise == 1
    assert one_paise.machine_paise == 1
    assert one_paise.total_paise == 2
    with pytest.raises(ValueError, match="10000"):
        calculate_pricing_v1(
            PricingInputs(
                filament_mg=0,
                duration_seconds=0,
                material_rate_paise_per_gram=0,
                machine_rate_paise_per_hour=0,
                setup_fee_paise=0,
                contingency_bps=10_001,
                minimum_order_paise=0,
                tax_bps=0,
            )
        )


async def _database() -> tuple[object, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def test_policy_activation_retires_previous_version_and_estimate_is_immutable() -> None:
    async def scenario() -> None:
        engine, sessions = await _database()
        now = datetime.now(UTC)
        owner = User(
            id=uuid4(),
            email="owner-pricing@example.com",
            display_name="Owner",
            password_hash="unused",
            role=Role.OWNER,
            owner_slot="primary",
            status=UserStatus.ACTIVE,
            email_verified_at=now,
            password_changed_at=now,
        )
        buyer = User(
            id=uuid4(),
            email="buyer-pricing@example.com",
            display_name="Buyer",
            password_hash="unused",
            role=Role.BUYER,
            status=UserStatus.ACTIVE,
            email_verified_at=now,
            password_changed_at=now,
        )
        quote = QuoteRequest(
            id=uuid4(),
            buyer_id=buyer.id,
            client_token=uuid4(),
            status=QuoteRequestStatus.ANALYSIS_READY,
            version=3,
            submitted_at=now,
            assets=[],
            analysis_runs=[],
            estimates=[],
        )
        analysis = AnalysisRun(
            id=uuid4(),
            quote_request_id=quote.id,
            request_version=2,
            status=AnalysisRunStatus.SUCCEEDED,
            attempt_count=1,
            validator_version="xxx-model-validator/1",
            slicer_name="OrcaSlicer",
            slicer_version="verified-test-version",
            profile_sha256="a" * 64,
            material_code="pla",
            queued_at=now,
            started_at=now,
            completed_at=now,
            asset_results=[],
        )
        asset = ModelAsset(
            id=uuid4(),
            quote_request_id=quote.id,
            client_token=uuid4(),
            original_filename="priced-part.stl",
            declared_format=ModelFormat.STL,
            declared_content_type="application/octet-stream",
            expected_size_bytes=1_024,
            actual_size_bytes=1_024,
            claimed_sha256="b" * 64,
            verified_sha256="b" * 64,
            storage_key=f"models/original/{buyer.id}/{quote.id}/{uuid4()}/source",
            status=ModelAssetStatus.VALIDATED,
            upload_expires_at=now,
            uploaded_at=now,
        )
        result = AnalysisAssetResult(
            id=uuid4(),
            analysis_run_id=analysis.id,
            model_asset_id=asset.id,
            status=AnalysisAssetStatus.SLICED,
            verified_sha256="b" * 64,
            warning_codes=[],
            filament_mg=12_500,
            duration_seconds=1_800,
        )
        analysis.asset_results.append(result)
        quote.assets.append(asset)
        quote.analysis_runs.append(analysis)
        async with sessions() as session:
            session.add_all((owner, buyer, quote))
            await session.commit()

        async with sessions() as session:
            first = await create_pricing_policy(
                session,
                owner=owner,
                machine_rate_paise_per_hour=10_000,
                setup_fee_paise=1_000,
                minimum_order_paise=10_000,
                contingency_bps=1_000,
                tax_bps=1_800,
                estimate_validity_hours=48,
                materials=[("petg", "PETG", 300), ("pla", "PLA", 200)],
                now=now,
            )
        async with sessions() as session:
            first = await activate_pricing_policy(
                session,
                owner=owner,
                policy_id=first.id,
                now=now,
            )

        estimate_token = uuid4()
        async with sessions() as session:
            with pytest.raises(PricingConflictError, match="does not match"):
                await create_quote_estimate(
                    session,
                    owner=owner,
                    quote_request_id=quote.id,
                    client_token=uuid4(),
                    expected_quote_version=3,
                    analysis_run_id=analysis.id,
                    material_code="petg",
                    now=now,
                )
        async with sessions() as session:
            estimate = await create_quote_estimate(
                session,
                owner=owner,
                quote_request_id=quote.id,
                client_token=estimate_token,
                expected_quote_version=3,
                analysis_run_id=analysis.id,
                material_code="pla",
                now=now,
            )
            estimate_id = estimate.id
            assert estimate.quote_request_version == 4
            assert estimate.total_paise == 11_800
            assert estimate.policy.version == 1

        async with sessions() as session:
            replay = await create_quote_estimate(
                session,
                owner=owner,
                quote_request_id=quote.id,
                client_token=estimate_token,
                expected_quote_version=3,
                analysis_run_id=analysis.id,
                material_code="pla",
                now=now,
            )
            assert replay.id == estimate_id
        async with sessions() as session:
            with pytest.raises(PricingConflictError, match="version changed"):
                await create_quote_estimate(
                    session,
                    owner=owner,
                    quote_request_id=quote.id,
                    client_token=uuid4(),
                    expected_quote_version=3,
                    analysis_run_id=analysis.id,
                    material_code="pla",
                    now=now,
                )

        async with sessions() as session:
            second = await create_pricing_policy(
                session,
                owner=owner,
                machine_rate_paise_per_hour=20_000,
                setup_fee_paise=2_000,
                minimum_order_paise=20_000,
                contingency_bps=0,
                tax_bps=0,
                estimate_validity_hours=24,
                materials=[("petg", "PETG", 300)],
                now=now,
            )
        async with sessions() as session:
            second = await activate_pricing_policy(
                session,
                owner=owner,
                policy_id=second.id,
                now=now,
            )
            assert second.status is PricingPolicyStatus.ACTIVE
        async with sessions() as session:
            persisted_first = await session.get(PricingPolicy, first.id)
            persisted_estimate = await session.scalar(
                select(QuoteEstimate).where(QuoteEstimate.id == estimate_id)
            )
            persisted_quote = await session.get(QuoteRequest, quote.id)
            assert persisted_first is not None
            assert persisted_first.status is PricingPolicyStatus.RETIRED
            assert persisted_estimate is not None
            assert persisted_estimate.total_paise == 11_800
            assert persisted_quote is not None
            assert persisted_quote.status is QuoteRequestStatus.ESTIMATE_READY
            assert persisted_quote.version == 4
        await engine.dispose()  # type: ignore[attr-defined]

    run(scenario())
