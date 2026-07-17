"""Database-authoritative analysis leases, completion, and outbox state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from xxx_api.domain.auth import AuditEventType
from xxx_api.domain.quotes import (
    AnalysisAssetStatus,
    AnalysisRunStatus,
    ModelAssetStatus,
    ModelFormat,
    QuoteRequestStatus,
)
from xxx_api.models.analysis import AnalysisAssetResult, AnalysisRun, OutboxEvent
from xxx_api.models.quotes import QuoteRequest
from xxx_api.services.audit import append_audit_event

SAFE_FAILURE_CODES = {
    "analysis_attempt_limit",
    "archive_compression_ratio_exceeded",
    "archive_duplicate_entry",
    "archive_entry_limit_exceeded",
    "archive_entry_too_large",
    "archive_expansion_limit_exceeded",
    "archive_link_forbidden",
    "archive_path_unsafe",
    "declared_format_unsupported",
    "digest_mismatch",
    "external_relationship_forbidden",
    "geometry_missing",
    "nested_archive_forbidden",
    "non_finite_coordinate",
    "obj_encoding_invalid",
    "obj_external_resource_forbidden",
    "obj_face_invalid",
    "obj_statement_unsupported",
    "obj_vertex_invalid",
    "object_limit_exceeded",
    "relationship_invalid",
    "size_mismatch",
    "sliced_artifact_forbidden",
    "source_changed_during_read",
    "source_empty",
    "source_too_large",
    "source_unavailable",
    "step_encoding_invalid",
    "step_signature_invalid",
    "step_structure_invalid",
    "stl_signature_invalid",
    "stl_structure_invalid",
    "stl_truncated",
    "three_mf_components_unsupported",
    "three_mf_model_invalid",
    "three_mf_model_missing",
    "three_mf_package_invalid",
    "three_mf_signature_invalid",
    "three_mf_triangle_invalid",
    "three_mf_unit_invalid",
    "three_mf_vertex_invalid",
    "triangle_limit_exceeded",
    "validator_output_invalid",
    "validator_timeout",
    "vertex_limit_exceeded",
    "worker_internal",
    "xml_declaration_forbidden",
    "xml_structure_invalid",
}


class AnalysisStateError(Exception):
    """The requested worker transition is stale or conflicts with persisted state."""


class AnalysisLeaseUnavailableError(AnalysisStateError):
    """Another non-expired worker lease owns the run."""


@dataclass(frozen=True, slots=True)
class ValidatedAssetEvidence:
    """Credential-free validator result accepted by the orchestration boundary."""

    asset_id: UUID
    detected_format: ModelFormat
    verified_sha256: str
    dimensions_um: tuple[int, int, int] | None
    triangle_count: int | None
    object_count: int | None
    fits_build_volume: bool | None
    warning_codes: tuple[str, ...]


def _utc_now(now: datetime | None) -> datetime:
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _run_query(run_id: UUID):
    return (
        select(AnalysisRun)
        .where(AnalysisRun.id == run_id)
        .options(
            selectinload(AnalysisRun.asset_results),
            selectinload(AnalysisRun.quote_request).selectinload(QuoteRequest.assets),
        )
    )


async def claim_analysis_run(
    session: AsyncSession,
    *,
    run_id: UUID,
    lease_token: UUID,
    lease_seconds: int,
    max_attempts: int,
    now: datetime | None = None,
) -> AnalysisRun | None:
    """Claim or reclaim one non-terminal run with a fenced database lease."""
    claimed_at = _utc_now(now)
    run = await session.scalar(_run_query(run_id).with_for_update())
    if run is None:
        await session.rollback()
        return None
    if run.status in {
        AnalysisRunStatus.AWAITING_PROFILE,
        AnalysisRunStatus.SUCCEEDED,
        AnalysisRunStatus.FAILED,
    }:
        await session.rollback()
        return None
    lease_expires_at = (
        _utc_now(run.lease_expires_at) if run.lease_expires_at is not None else None
    )
    if (
        run.status is AnalysisRunStatus.RUNNING
        and lease_expires_at is not None
        and lease_expires_at > claimed_at
    ):
        await session.rollback()
        raise AnalysisLeaseUnavailableError
    quote = run.quote_request
    if quote.version != run.request_version or quote.status is not QuoteRequestStatus.ANALYZING:
        await session.rollback()
        raise AnalysisStateError("analysis input version is no longer current")
    if run.attempt_count >= max_attempts:
        await _fail_locked_run(
            session,
            run,
            failure_code="analysis_attempt_limit",
            failed_at=claimed_at,
        )
        await session.commit()
        return None
    active_assets = [
        asset for asset in quote.assets if asset.status is not ModelAssetStatus.REJECTED
    ]
    if not active_assets or any(
        asset.status not in {ModelAssetStatus.QUARANTINED, ModelAssetStatus.VALIDATING}
        for asset in active_assets
    ):
        await session.rollback()
        raise AnalysisStateError("analysis assets are not claimable")
    run.status = AnalysisRunStatus.RUNNING
    run.lease_token = lease_token
    run.lease_expires_at = claimed_at + timedelta(seconds=lease_seconds)
    run.attempt_count += 1
    run.started_at = run.started_at or claimed_at
    run.failure_code = None
    for asset in active_assets:
        asset.status = ModelAssetStatus.VALIDATING
    append_audit_event(
        session,
        AuditEventType.ANALYSIS_RUN_STARTED,
        occurred_at=claimed_at,
        target_user_id=quote.buyer_id,
        details={
            "quote_request_id": str(quote.id),
            "analysis_run_id": str(run.id),
            "attempt": run.attempt_count,
        },
    )
    await session.commit()
    return run


def _validate_evidence(run: AnalysisRun, evidence: list[ValidatedAssetEvidence]) -> None:
    active_assets = [
        asset
        for asset in run.quote_request.assets
        if asset.status is ModelAssetStatus.VALIDATING
    ]
    expected_ids = {asset.id for asset in active_assets}
    received_ids = {item.asset_id for item in evidence}
    if len(received_ids) != len(evidence) or received_ids != expected_ids:
        raise AnalysisStateError("analysis evidence does not match the claimed assets")
    by_id = {asset.id: asset for asset in active_assets}
    for item in evidence:
        asset = by_id[item.asset_id]
        if item.verified_sha256 != asset.claimed_sha256:
            raise AnalysisStateError("analysis evidence digest does not match the source claim")
        if item.detected_format is not asset.declared_format:
            raise AnalysisStateError("analysis evidence format does not match the declaration")
        if len(item.warning_codes) > 32 or any(
            not code or len(code) > 64 for code in item.warning_codes
        ):
            raise AnalysisStateError("analysis evidence warnings are invalid")


async def complete_validation_awaiting_profile(
    session: AsyncSession,
    *,
    run_id: UUID,
    lease_token: UUID,
    evidence: list[ValidatedAssetEvidence],
    now: datetime | None = None,
) -> AnalysisRun:
    """Persist verified source evidence without inventing unavailable slicer metrics."""
    completed_at = _utc_now(now)
    run = await session.scalar(_run_query(run_id).with_for_update())
    if (
        run is None
        or run.status is not AnalysisRunStatus.RUNNING
        or run.lease_token != lease_token
    ):
        await session.rollback()
        raise AnalysisStateError("analysis lease is stale")
    _validate_evidence(run, evidence)
    by_id = {asset.id: asset for asset in run.quote_request.assets}
    for item in evidence:
        asset = by_id[item.asset_id]
        asset.status = ModelAssetStatus.VALIDATED
        asset.verified_sha256 = item.verified_sha256
        session.add(
            AnalysisAssetResult(
                analysis_run_id=run.id,
                model_asset_id=asset.id,
                status=AnalysisAssetStatus.AWAITING_PROFILE,
                detected_format=item.detected_format,
                verified_sha256=item.verified_sha256,
                dimension_x_um=(item.dimensions_um[0] if item.dimensions_um else None),
                dimension_y_um=(item.dimensions_um[1] if item.dimensions_um else None),
                dimension_z_um=(item.dimensions_um[2] if item.dimensions_um else None),
                triangle_count=item.triangle_count,
                object_count=item.object_count,
                fits_build_volume=item.fits_build_volume,
                warning_codes=list(item.warning_codes),
                failure_code=None,
                created_at=completed_at,
                updated_at=completed_at,
            )
        )
    run.status = AnalysisRunStatus.AWAITING_PROFILE
    run.completed_at = completed_at
    run.lease_token = None
    run.lease_expires_at = None
    run.quote_request.status = QuoteRequestStatus.ANALYSIS_READY
    run.quote_request.version += 1
    append_audit_event(
        session,
        AuditEventType.ANALYSIS_RUN_AWAITING_PROFILE,
        occurred_at=completed_at,
        target_user_id=run.quote_request.buyer_id,
        details={
            "quote_request_id": str(run.quote_request.id),
            "analysis_run_id": str(run.id),
            "model_count": len(evidence),
        },
    )
    await session.commit()
    return run


async def _fail_locked_run(
    session: AsyncSession,
    run: AnalysisRun,
    *,
    failure_code: str,
    failed_at: datetime,
    failed_asset_id: UUID | None = None,
) -> None:
    if failure_code not in SAFE_FAILURE_CODES:
        raise AnalysisStateError("analysis failure code is not allowlisted")
    run.status = AnalysisRunStatus.FAILED
    run.failure_code = failure_code
    run.completed_at = failed_at
    run.lease_token = None
    run.lease_expires_at = None
    run.quote_request.status = QuoteRequestStatus.ANALYSIS_FAILED
    run.quote_request.version += 1
    for asset in run.quote_request.assets:
        if asset.status is ModelAssetStatus.VALIDATING:
            if failed_asset_id is None or asset.id == failed_asset_id:
                asset.status = ModelAssetStatus.REJECTED
                asset.rejection_code = failure_code
            else:
                asset.status = ModelAssetStatus.QUARANTINED
    append_audit_event(
        session,
        AuditEventType.ANALYSIS_RUN_FAILED,
        occurred_at=failed_at,
        target_user_id=run.quote_request.buyer_id,
        details={
            "quote_request_id": str(run.quote_request.id),
            "analysis_run_id": str(run.id),
            "failure_code": failure_code,
            **(
                {"model_asset_id": str(failed_asset_id)}
                if failed_asset_id is not None
                else {}
            ),
        },
    )


async def fail_analysis_run(
    session: AsyncSession,
    *,
    run_id: UUID,
    lease_token: UUID,
    failure_code: str,
    failed_asset_id: UUID | None = None,
    now: datetime | None = None,
) -> AnalysisRun:
    """Finalize one leased run with an allowlisted buyer-safe failure code."""
    failed_at = _utc_now(now)
    run = await session.scalar(_run_query(run_id).with_for_update())
    if (
        run is None
        or run.status is not AnalysisRunStatus.RUNNING
        or run.lease_token != lease_token
    ):
        await session.rollback()
        raise AnalysisStateError("analysis lease is stale")
    await _fail_locked_run(
        session,
        run,
        failure_code=failure_code,
        failed_at=failed_at,
        failed_asset_id=failed_asset_id,
    )
    await session.commit()
    return run


async def pending_outbox_events(
    session: AsyncSession,
    *,
    limit: int,
    now: datetime | None = None,
) -> list[OutboxEvent]:
    """Read a bounded batch; duplicate publication remains safe by design."""
    current = _utc_now(now)
    return list(
        await session.scalars(
            select(OutboxEvent)
            .where(
                OutboxEvent.published_at.is_(None),
                OutboxEvent.available_at <= current,
            )
            .order_by(OutboxEvent.available_at, OutboxEvent.id)
            .limit(limit)
        )
    )


async def mark_outbox_published(
    session: AsyncSession,
    *,
    event_id: UUID,
    now: datetime | None = None,
) -> None:
    """Mark one event after successful at-least-once stream publication."""
    event = await session.get(OutboxEvent, event_id, with_for_update=True)
    if event is None:
        await session.rollback()
        return
    if event.published_at is None:
        event.published_at = _utc_now(now)
        event.attempt_count += 1
        event.last_error_code = None
        await session.commit()
    else:
        await session.rollback()
