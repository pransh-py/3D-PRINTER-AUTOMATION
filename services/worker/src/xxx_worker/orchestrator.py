"""At-least-once analysis orchestration around the isolated validator."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from xxx_api.config import Settings
from xxx_api.domain.quotes import ModelAssetStatus, ModelFormat
from xxx_api.models.analysis import OutboxEvent
from xxx_api.models.quotes import ModelAsset
from xxx_api.services.analysis import (
    AnalysisLeaseUnavailableError,
    AnalysisStateError,
    ValidatedAssetEvidence,
    claim_analysis_run,
    complete_validation_awaiting_profile,
    fail_analysis_run,
    mark_outbox_published,
    pending_outbox_events,
)
from xxx_api.services.quotes import ANALYSIS_TOPIC
from xxx_api.storage import ObjectStorage, ObjectStorageError

from xxx_worker.queue import AnalysisQueue, AnalysisQueueMessage
from xxx_worker.sandbox import SandboxValidator
from xxx_worker.validation import ModelFormat as WorkerModelFormat
from xxx_worker.validation import ModelValidationError


class DeliveryDisposition(StrEnum):
    """Whether the Redis Stream delivery may be acknowledged."""

    ACKNOWLEDGE = "acknowledge"
    RETRY = "retry"


@dataclass(slots=True)
class AnalysisOrchestrator:
    """Coordinate storage, sandbox, and fenced database transitions."""

    settings: Settings
    sessions: async_sessionmaker[AsyncSession]
    storage: ObjectStorage
    validator: SandboxValidator

    async def process(self, message: AnalysisQueueMessage) -> DeliveryDisposition:
        lease_token = uuid4()
        try:
            async with self.sessions() as session:
                run = await claim_analysis_run(
                    session,
                    run_id=message.analysis_run_id,
                    lease_token=lease_token,
                    lease_seconds=self.settings.analysis_lease_seconds,
                    max_attempts=self.settings.analysis_max_attempts,
                )
        except AnalysisLeaseUnavailableError:
            return DeliveryDisposition.RETRY
        except AnalysisStateError:
            return DeliveryDisposition.ACKNOWLEDGE
        if run is None:
            return DeliveryDisposition.ACKNOWLEDGE

        try:
            evidence = await self._validate_assets(run.quote_request.assets)
            async with self.sessions() as session:
                await complete_validation_awaiting_profile(
                    session,
                    run_id=run.id,
                    lease_token=lease_token,
                    evidence=evidence,
                )
        except _AssetValidationFailureError as error:
            async with self.sessions() as session:
                try:
                    await fail_analysis_run(
                        session,
                        run_id=run.id,
                        lease_token=lease_token,
                        failure_code=error.failure_code,
                        failed_asset_id=error.asset_id,
                    )
                except AnalysisStateError:
                    return DeliveryDisposition.RETRY
        except ObjectStorageError:
            return DeliveryDisposition.RETRY
        except AnalysisStateError:
            return DeliveryDisposition.RETRY
        return DeliveryDisposition.ACKNOWLEDGE

    async def _validate_assets(
        self,
        assets: list[ModelAsset],
    ) -> list[ValidatedAssetEvidence]:
        validated: list[ValidatedAssetEvidence] = []
        with TemporaryDirectory(prefix="xxx-analysis-") as scratch_value:
            scratch = Path(scratch_value)
            for asset in assets:
                if asset.status is not ModelAssetStatus.VALIDATING:
                    continue
                source = scratch / f"asset-{asset.id}"
                await self.storage.download_to_path(
                    asset.storage_key,
                    source,
                    max_bytes=self.settings.max_model_file_bytes,
                )
                try:
                    result = await self.validator.validate(
                        source,
                        declared_format=cast(WorkerModelFormat, asset.declared_format.value),
                        expected_size=asset.expected_size_bytes,
                        claimed_sha256=asset.claimed_sha256,
                        scratch_directory=scratch,
                    )
                except ModelValidationError as error:
                    raise _AssetValidationFailureError(asset.id, error.code) from None
                validated.append(
                    ValidatedAssetEvidence(
                        asset_id=asset.id,
                        detected_format=ModelFormat(result.detected_format),
                        verified_sha256=result.verified_sha256,
                        dimensions_um=result.dimensions_um,
                        triangle_count=result.triangle_count,
                        object_count=result.object_count,
                        fits_build_volume=result.fits_build_volume,
                        warning_codes=result.warning_codes,
                    )
                )
                source.unlink(missing_ok=True)
        return validated


class _AssetValidationFailureError(Exception):
    def __init__(self, asset_id: UUID, failure_code: str) -> None:
        self.asset_id = asset_id
        self.failure_code = failure_code
        super().__init__(failure_code)


async def dispatch_analysis_outbox(
    sessions: async_sessionmaker[AsyncSession],
    queue: AnalysisQueue,
    *,
    limit: int = 20,
) -> int:
    """Publish a bounded outbox batch, accepting harmless duplicate delivery."""
    async with sessions() as session:
        events = await pending_outbox_events(session, limit=limit)
    published = 0
    for event in events:
        if event.topic != ANALYSIS_TOPIC:
            continue
        run_id = _outbox_run_id(event)
        await queue.publish(event_id=event.id, run_id=run_id)
        async with sessions() as session:
            await mark_outbox_published(session, event_id=event.id)
        published += 1
    return published


def _outbox_run_id(event: OutboxEvent) -> UUID:
    value = event.payload.get("analysis_run_id")
    if not isinstance(value, str):
        raise AnalysisStateError("analysis outbox payload is invalid")
    try:
        run_id = UUID(value)
    except ValueError as error:
        raise AnalysisStateError("analysis outbox payload is invalid") from error
    if run_id != event.aggregate_id or event.aggregate_type != "analysis_run":
        raise AnalysisStateError("analysis outbox aggregate is invalid")
    return run_id
