"""End-to-end validator orchestration with real subprocess and in-memory persistence."""

from asyncio import run
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from struct import Struct, pack
from typing import cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from xxx_api.config import Settings
from xxx_api.domain.auth import UserStatus
from xxx_api.domain.quotes import (
    AnalysisRunStatus,
    ModelAssetStatus,
    ModelFormat,
    QuoteRequestStatus,
)
from xxx_api.domain.roles import Role
from xxx_api.models import AnalysisRun, Base, User
from xxx_api.models.quotes import ModelAsset, QuoteRequest
from xxx_api.storage import ObjectStorage

from xxx_worker.orchestrator import AnalysisOrchestrator, DeliveryDisposition
from xxx_worker.queue import AnalysisQueueMessage
from xxx_worker.sandbox import SandboxValidator

TRIANGLE = Struct("<12fH")


class FakeStorage:
    def __init__(self, data: bytes) -> None:
        self.data = data

    async def download_to_path(
        self,
        _key: str,
        destination: Path,
        *,
        max_bytes: int,
    ) -> int:
        assert len(self.data) <= max_bytes
        destination.write_bytes(self.data)
        return len(self.data)


def _model_bytes() -> bytes:
    return (
        b"orchestrator fixture".ljust(80, b" ")
        + pack("<I", 1)
        + TRIANGLE.pack(
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            2.0,
            0.0,
            0.0,
            0.0,
            3.0,
            0.0,
            0,
        )
    )


async def _seed(
    data: bytes,
) -> tuple[async_sessionmaker[AsyncSession], AnalysisRun, ModelAsset, QuoteRequest]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    now = datetime.now(UTC)
    buyer = User(
        id=uuid4(),
        email="worker@example.com",
        display_name="Worker Buyer",
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
        expected_size_bytes=len(data),
        actual_size_bytes=len(data),
        claimed_sha256=sha256(data).hexdigest(),
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
    return sessions, analysis, asset, quote


def test_orchestrator_validates_and_stops_at_awaiting_profile() -> None:
    async def scenario() -> None:
        data = _model_bytes()
        sessions, analysis, asset, quote = await _seed(data)
        settings = Settings(environment="test", analysis_validator_timeout_seconds=5)
        orchestrator = AnalysisOrchestrator(
            settings=settings,
            sessions=sessions,
            storage=cast(ObjectStorage, FakeStorage(data)),
            validator=SandboxValidator(command="xxx-analyzer", timeout_seconds=5),
        )
        disposition = await orchestrator.process(
            AnalysisQueueMessage(
                stream_id="1-0",
                outbox_event_id=uuid4(),
                analysis_run_id=analysis.id,
            )
        )
        assert disposition is DeliveryDisposition.ACKNOWLEDGE
        async with sessions() as session:
            persisted_run = await session.get(AnalysisRun, analysis.id)
            persisted_asset = await session.get(ModelAsset, asset.id)
            persisted_quote = await session.get(QuoteRequest, quote.id)
            assert persisted_run is not None
            assert persisted_run.status is AnalysisRunStatus.AWAITING_PROFILE
            assert persisted_asset is not None
            assert persisted_asset.status is ModelAssetStatus.VALIDATED
            assert persisted_asset.verified_sha256 == sha256(data).hexdigest()
            assert persisted_quote is not None
            assert persisted_quote.status is QuoteRequestStatus.ANALYSIS_READY

    run(scenario())
