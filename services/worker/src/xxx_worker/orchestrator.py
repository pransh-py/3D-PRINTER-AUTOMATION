"""At-least-once analysis orchestration around the isolated validator."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import file_digest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from xxx_api.config import Settings
from xxx_api.domain.quotes import ModelAssetStatus, ModelFormat
from xxx_api.models.analysis import OutboxEvent
from xxx_api.models.quotes import ModelAsset
from xxx_api.print_presets import PresetConfigurationError, load_print_presets
from xxx_api.services.analysis import (
    AnalysisLeaseUnavailableError,
    AnalysisStateError,
    SlicedAssetEvidence,
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
from xxx_worker.slicing import OrcaSlicer
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
            selected_settings = self.settings
            specification = run.quote_request.print_specification
            if specification:
                try:
                    preset = next(
                        (
                            item
                            for item in load_print_presets(self.settings)
                            if item.code == specification.get("presetCode")
                        ),
                        None,
                    )
                    colour = specification.get("colour")
                    if colour is not None and not isinstance(colour, str):
                        raise PresetConfigurationError("Invalid captured colour.")
                    if preset is None or preset.specification(colour) != specification:
                        raise PresetConfigurationError("The selected print offering changed.")
                    selected_settings = self.settings.model_copy(
                        update={
                            "analysis_profile_directory": preset.profile_directory,
                            "analysis_profile_sha256": preset.profile_sha256,
                            "analysis_material_code": preset.material_code,
                        }
                    )
                except PresetConfigurationError:
                    raise _AssetValidationFailureError(
                        run.quote_request.assets[0].id, "slicer_profile_changed"
                    ) from None
            elif self.settings.analysis_profile_directory is None:
                selected_settings = self.settings.model_copy(
                    update={"analysis_slicer_command": None}
                )
            evidence, slices = await self._validate_assets(
                run.quote_request.assets,
                slicing_settings=selected_settings,
            )
            async with self.sessions() as session:
                await complete_validation_awaiting_profile(
                    session,
                    run_id=run.id,
                    lease_token=lease_token,
                    evidence=evidence,
                    slices=slices if selected_settings.analysis_slicer_command else None,
                    slicer_version=self.settings.analysis_slicer_version,
                    material_code=selected_settings.analysis_material_code,
                    print_preset_code=str(specification["presetCode"]) if specification else None,
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
        *,
        slicing_settings: Settings | None = None,
    ) -> tuple[list[ValidatedAssetEvidence], list[SlicedAssetEvidence]]:
        validated: list[ValidatedAssetEvidence] = []
        sliced: list[SlicedAssetEvidence] = []
        selected_settings = slicing_settings or self.settings
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
                if selected_settings.analysis_slicer_command:
                    if result.fits_build_volume is False:
                        raise _AssetValidationFailureError(asset.id, "build_volume_exceeded")
                    slice_directory = scratch / f"slice-{asset.id}"
                    slice_directory.mkdir()
                    # The source is copied into the only writable/visible sandbox directory.
                    slice_source = slice_directory / f"source.{asset.declared_format.value}"
                    source.rename(slice_source)
                    try:
                        output = await OrcaSlicer(selected_settings).slice(
                            slice_source, slice_directory
                        )
                    except ModelValidationError as error:
                        raise _AssetValidationFailureError(asset.id, error.code) from None
                    artifact_key = (
                        f"models/derived/{asset.quote_request_id}/{asset.id}/"
                        f"{output.artifact_sha256}.gcode"
                    )
                    await self.storage.upload_from_path(
                        artifact_key, output.artifact, content_type="application/octet-stream"
                    )
                    preview_key = None
                    preview_hash = None
                    if output.preview:
                        with output.preview.open("rb") as preview_file:
                            preview_hash = file_digest(preview_file, "sha256").hexdigest()
                        preview_key = (
                            f"models/derived/{asset.quote_request_id}/{asset.id}/{preview_hash}.png"
                        )
                        await self.storage.upload_from_path(
                            preview_key, output.preview, content_type="image/png"
                        )
                    sliced.append(
                        SlicedAssetEvidence(
                            asset.id,
                            output.filament_mg,
                            output.duration_seconds,
                            artifact_key,
                            output.artifact_sha256,
                            output.profile_sha256,
                            preview_key,
                            preview_hash,
                        )
                    )
                source.unlink(missing_ok=True)
        return validated, sliced


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
