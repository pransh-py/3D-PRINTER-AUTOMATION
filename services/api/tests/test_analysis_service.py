"""Fenced analysis lease and terminal transition tests."""

from asyncio import run
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from xxx_api.domain.auth import UserStatus
from xxx_api.domain.quotes import (
    AnalysisAssetStatus,
    AnalysisRunStatus,
    ModelAssetStatus,
    ModelFormat,
    QuoteRequestStatus,
)
from xxx_api.domain.roles import Role
from xxx_api.models import AnalysisAssetResult, AnalysisRun, Base, User
from xxx_api.models.quotes import ModelAsset, QuoteRequest
from xxx_api.services.analysis import (
    AnalysisLeaseUnavailableError,
    AnalysisStateError,
    ValidatedAssetEvidence,
    claim_analysis_run,
    complete_validation_awaiting_profile,
    fail_analysis_run,
)


async def _database() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def _queued_run(
    sessions: async_sessionmaker[AsyncSession],
) -> tuple[AnalysisRun, ModelAsset]:
    now = datetime.now(UTC)
    buyer = User(
        id=uuid4(),
        email="analysis@example.com",
        display_name="Analysis Buyer",
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
        status=QuoteRequestStatus.ANALYZING,
        version=2,
        submitted_at=now,
        assets=[],
        analysis_runs=[],
    )
    asset = ModelAsset(
        id=uuid4(),
        quote_request_id=quote.id,
        client_token=uuid4(),
        original_filename="part.stl",
        declared_format=ModelFormat.STL,
        declared_content_type="application/octet-stream",
        expected_size_bytes=134,
        actual_size_bytes=134,
        claimed_sha256="a" * 64,
        storage_key=f"models/original/{buyer.id}/{quote.id}/{uuid4()}/source",
        status=ModelAssetStatus.QUARANTINED,
        upload_expires_at=now + timedelta(minutes=10),
        uploaded_at=now,
    )
    analysis = AnalysisRun(
        id=uuid4(),
        quote_request_id=quote.id,
        request_version=2,
        status=AnalysisRunStatus.QUEUED,
        attempt_count=0,
        validator_version="xxx-model-validator/1",
        queued_at=now,
        asset_results=[],
    )
    quote.assets.append(asset)
    quote.analysis_runs.append(analysis)
    async with sessions() as session:
        session.add_all((buyer, quote))
        await session.commit()
    return analysis, asset


def test_claim_is_fenced_and_completion_persists_safe_evidence() -> None:
    async def scenario() -> None:
        sessions = await _database()
        analysis, asset = await _queued_run(sessions)
        token = uuid4()
        claimed_at = datetime.now(UTC)
        async with sessions() as session:
            claimed = await claim_analysis_run(
                session,
                run_id=analysis.id,
                lease_token=token,
                lease_seconds=600,
                max_attempts=3,
                now=claimed_at,
            )
            assert claimed is not None
            assert claimed.status is AnalysisRunStatus.RUNNING
            assert claimed.attempt_count == 1
            assert claimed.quote_request.assets[0].status is ModelAssetStatus.VALIDATING
        async with sessions() as session:
            with pytest.raises(AnalysisLeaseUnavailableError):
                await claim_analysis_run(
                    session,
                    run_id=analysis.id,
                    lease_token=uuid4(),
                    lease_seconds=600,
                    max_attempts=3,
                    now=claimed_at + timedelta(seconds=1),
                )
        evidence = ValidatedAssetEvidence(
            asset_id=asset.id,
            detected_format=ModelFormat.STL,
            verified_sha256="a" * 64,
            dimensions_um=(10_000, 20_000, 30_000),
            triangle_count=1,
            object_count=1,
            fits_build_volume=True,
            warning_codes=(),
        )
        async with sessions() as session:
            completed = await complete_validation_awaiting_profile(
                session,
                run_id=analysis.id,
                lease_token=token,
                evidence=[evidence],
                now=claimed_at + timedelta(seconds=2),
            )
            assert completed.status is AnalysisRunStatus.AWAITING_PROFILE
            assert completed.quote_request.status is QuoteRequestStatus.ANALYSIS_READY
            assert completed.quote_request.version == 3
        async with sessions() as session:
            result = await session.scalar(select(AnalysisAssetResult))
            assert result is not None
            assert result.status is AnalysisAssetStatus.AWAITING_PROFILE
            assert result.verified_sha256 == "a" * 64
            assert result.dimension_x_um == 10_000
            persisted_asset = await session.get(ModelAsset, asset.id)
            assert persisted_asset is not None
            assert persisted_asset.status is ModelAssetStatus.VALIDATED
            assert persisted_asset.verified_sha256 == "a" * 64

    run(scenario())


def test_expired_lease_can_be_reclaimed_but_stale_token_cannot_finish() -> None:
    async def scenario() -> None:
        sessions = await _database()
        analysis, _ = await _queued_run(sessions)
        first_token = uuid4()
        second_token = uuid4()
        start = datetime.now(UTC)
        async with sessions() as session:
            await claim_analysis_run(
                session,
                run_id=analysis.id,
                lease_token=first_token,
                lease_seconds=120,
                max_attempts=3,
                now=start,
            )
        async with sessions() as session:
            reclaimed = await claim_analysis_run(
                session,
                run_id=analysis.id,
                lease_token=second_token,
                lease_seconds=120,
                max_attempts=3,
                now=start + timedelta(seconds=121),
            )
            assert reclaimed is not None
            assert reclaimed.attempt_count == 2
        async with sessions() as session:
            with pytest.raises(AnalysisStateError, match="lease is stale"):
                await fail_analysis_run(
                    session,
                    run_id=analysis.id,
                    lease_token=first_token,
                    failure_code="worker_internal",
                    now=start + timedelta(seconds=122),
                )

    run(scenario())


def test_failure_codes_are_allowlisted_and_reject_only_the_failed_asset() -> None:
    async def scenario() -> None:
        sessions = await _database()
        analysis, asset = await _queued_run(sessions)
        token = uuid4()
        async with sessions() as session:
            await claim_analysis_run(
                session,
                run_id=analysis.id,
                lease_token=token,
                lease_seconds=600,
                max_attempts=3,
            )
        async with sessions() as session:
            with pytest.raises(AnalysisStateError, match="not allowlisted"):
                await fail_analysis_run(
                    session,
                    run_id=analysis.id,
                    lease_token=token,
                    failure_code="raw exception with private path",
                    failed_asset_id=asset.id,
                )
        async with sessions() as session:
            failed = await fail_analysis_run(
                session,
                run_id=analysis.id,
                lease_token=token,
                failure_code="digest_mismatch",
                failed_asset_id=asset.id,
            )
            assert failed.status is AnalysisRunStatus.FAILED
            assert failed.quote_request.status is QuoteRequestStatus.ANALYSIS_FAILED
            assert failed.quote_request.assets[0].status is ModelAssetStatus.REJECTED
            assert failed.quote_request.assets[0].rejection_code == "digest_mismatch"

    run(scenario())
