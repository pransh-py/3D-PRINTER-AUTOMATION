"""Transactional versioned pricing and immutable estimate creation."""

from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from xxx_api.domain.auth import AuditEventType
from xxx_api.domain.pricing import (
    PricingInputs,
    PricingPolicyStatus,
    calculate_pricing_v1,
)
from xxx_api.domain.quotes import AnalysisAssetStatus, AnalysisRunStatus, QuoteRequestStatus
from xxx_api.models.analysis import AnalysisRun
from xxx_api.models.commerce import Quote
from xxx_api.models.identity import User
from xxx_api.models.pricing import MaterialRate, PricingPolicy, QuoteEstimate
from xxx_api.models.quotes import QuoteRequest
from xxx_api.services.audit import append_audit_event

CALCULATION_VERSION = "pricing-v1"


class PricingError(Exception):
    """Base pricing-domain failure translated by HTTP adapters."""


class PricingConflictError(PricingError):
    """The requested operation conflicts with persisted pricing state."""


class PricingNotFoundError(PricingError):
    """The requested owner-visible pricing resource does not exist."""


def _utc_now(now: datetime | None) -> datetime:
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def list_pricing_policies(session: AsyncSession) -> list[PricingPolicy]:
    """List all immutable policy versions newest-first for the owner."""
    return list(
        await session.scalars(
            select(PricingPolicy)
            .options(selectinload(PricingPolicy.materials))
            .order_by(PricingPolicy.version.desc())
        )
    )


async def create_pricing_policy(
    session: AsyncSession,
    *,
    owner: User,
    machine_rate_paise_per_hour: int,
    setup_fee_paise: int,
    minimum_order_paise: int,
    contingency_bps: int,
    tax_bps: int,
    estimate_validity_hours: int,
    materials: list[tuple[str, str, int]],
    now: datetime | None = None,
    audit_request_id: str | None = None,
) -> PricingPolicy:
    """Create a complete draft; policy contents have no update operation."""
    created_at = _utc_now(now)
    latest_version = await session.scalar(select(func.max(PricingPolicy.version)))
    policy = PricingPolicy(
        id=uuid4(),
        version=int(latest_version or 0) + 1,
        status=PricingPolicyStatus.DRAFT,
        currency="INR",
        machine_rate_paise_per_hour=machine_rate_paise_per_hour,
        setup_fee_paise=setup_fee_paise,
        minimum_order_paise=minimum_order_paise,
        contingency_bps=contingency_bps,
        tax_bps=tax_bps,
        estimate_validity_hours=estimate_validity_hours,
        created_by_user_id=owner.id,
        created_at=created_at,
        updated_at=created_at,
        materials=[
            MaterialRate(
                id=uuid4(),
                code=code,
                display_name=display_name,
                rate_paise_per_gram=rate,
                created_at=created_at,
                updated_at=created_at,
            )
            for code, display_name, rate in materials
        ],
    )
    session.add(policy)
    append_audit_event(
        session,
        AuditEventType.PRICING_POLICY_CREATED,
        occurred_at=created_at,
        actor_user_id=owner.id,
        request_id=audit_request_id,
        details={"pricing_policy_id": str(policy.id), "version": policy.version},
    )
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise PricingConflictError("pricing policy version changed; retry") from error
    return policy


async def activate_pricing_policy(
    session: AsyncSession,
    *,
    owner: User,
    policy_id: UUID,
    now: datetime | None = None,
    audit_request_id: str | None = None,
) -> PricingPolicy:
    """Atomically retire the current policy and activate one draft."""
    policy = await session.scalar(
        select(PricingPolicy)
        .where(PricingPolicy.id == policy_id)
        .options(selectinload(PricingPolicy.materials))
        .with_for_update()
    )
    if policy is None:
        await session.rollback()
        raise PricingNotFoundError
    if policy.status is PricingPolicyStatus.ACTIVE:
        return policy
    if policy.status is not PricingPolicyStatus.DRAFT:
        await session.rollback()
        raise PricingConflictError("only a draft policy can be activated")
    activated_at = _utc_now(now)
    current = await session.scalar(
        select(PricingPolicy)
        .where(PricingPolicy.status == PricingPolicyStatus.ACTIVE)
        .with_for_update()
    )
    if current is not None:
        current.status = PricingPolicyStatus.RETIRED
        current.updated_at = activated_at
        await session.flush()
    policy.status = PricingPolicyStatus.ACTIVE
    policy.activated_at = activated_at
    policy.activated_by_user_id = owner.id
    policy.updated_at = activated_at
    append_audit_event(
        session,
        AuditEventType.PRICING_POLICY_ACTIVATED,
        occurred_at=activated_at,
        actor_user_id=owner.id,
        request_id=audit_request_id,
        details={"pricing_policy_id": str(policy.id), "version": policy.version},
    )
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise PricingConflictError("another policy activation won; reload and retry") from error
    return policy


async def create_quote_estimate(
    session: AsyncSession,
    *,
    owner: User | None,
    quote_request_id: UUID,
    client_token: UUID,
    expected_quote_version: int,
    analysis_run_id: UUID,
    material_code: str,
    now: datetime | None = None,
    audit_request_id: str | None = None,
) -> QuoteEstimate:
    """Create or return an immutable estimate from exact successful analysis evidence."""
    existing_by_token = await session.scalar(
        select(QuoteEstimate)
        .where(
            QuoteEstimate.quote_request_id == quote_request_id,
            QuoteEstimate.client_token == client_token,
        )
        .options(selectinload(QuoteEstimate.policy))
    )
    if existing_by_token is not None:
        if (
            existing_by_token.analysis_run_id != analysis_run_id
            or existing_by_token.material_code != material_code
        ):
            raise PricingConflictError("client token was already used for different inputs")
        return existing_by_token
    quote = await session.scalar(
        select(QuoteRequest)
        .where(QuoteRequest.id == quote_request_id)
        .options(selectinload(QuoteRequest.assets))
        .with_for_update()
    )
    if quote is None:
        await session.rollback()
        raise PricingNotFoundError
    if quote.version != expected_quote_version:
        await session.rollback()
        raise PricingConflictError("quote version changed; reload before estimating")
    if owner is None and (
        quote.status is not QuoteRequestStatus.ANALYSIS_READY
        or quote.print_specification is None
        or await session.scalar(
            select(QuoteEstimate.id).where(QuoteEstimate.quote_request_id == quote.id).limit(1)
        )
    ):
        await session.rollback()
        raise PricingConflictError("automatic estimation must not replace an existing quotation")
    if quote.status not in {
        QuoteRequestStatus.ANALYSIS_READY,
        QuoteRequestStatus.ESTIMATE_READY,
        QuoteRequestStatus.OWNER_REVIEW,
        QuoteRequestStatus.QUOTED,
    }:
        await session.rollback()
        raise PricingConflictError("quote does not have successful sliced analysis")
    if await session.scalar(
        select(Quote.id).where(Quote.quote_request_id == quote.id, Quote.status == "accepted")
    ):
        await session.rollback()
        raise PricingConflictError("an accepted quotation cannot be recalculated")

    analysis = await session.scalar(
        select(AnalysisRun)
        .where(
            AnalysisRun.id == analysis_run_id,
            AnalysisRun.quote_request_id == quote.id,
        )
        .options(selectinload(AnalysisRun.asset_results))
    )
    if analysis is None:
        await session.rollback()
        raise PricingNotFoundError
    if analysis.status is not AnalysisRunStatus.SUCCEEDED or not analysis.asset_results:
        await session.rollback()
        raise PricingConflictError("analysis is not a complete successful slice")
    if (
        analysis.slicer_name is None
        or analysis.slicer_version is None
        or analysis.profile_sha256 is None
        or analysis.material_code is None
    ):
        await session.rollback()
        raise PricingConflictError("analysis is missing slicer or material-profile evidence")
    specification = quote.print_specification
    if specification is not None and (
        analysis.print_preset_code != specification.get("presetCode")
        or analysis.profile_sha256 != specification.get("profileSha256")
        or analysis.material_code != specification.get("materialCode")
    ):
        await session.rollback()
        raise PricingConflictError("analysis does not match the selected print specification")
    if {result.model_asset_id for result in analysis.asset_results} != {
        asset.id for asset in quote.assets
    }:
        await session.rollback()
        raise PricingConflictError("analysis does not cover every quote asset")
    if any(
        result.status is not AnalysisAssetStatus.SLICED
        or result.filament_mg is None
        or result.duration_seconds is None
        for result in analysis.asset_results
    ):
        await session.rollback()
        raise PricingConflictError("analysis metrics are incomplete")

    policy = await session.scalar(
        select(PricingPolicy)
        .where(PricingPolicy.status == PricingPolicyStatus.ACTIVE)
        .options(selectinload(PricingPolicy.materials))
    )
    if policy is None:
        await session.rollback()
        raise PricingConflictError("no active pricing policy")
    material = next((item for item in policy.materials if item.code == material_code), None)
    if material is None:
        await session.rollback()
        raise PricingConflictError("material is not offered by the active pricing policy")
    if material.code != analysis.material_code:
        await session.rollback()
        raise PricingConflictError("selected material does not match the sliced profile")

    existing = await session.scalar(
        select(QuoteEstimate)
        .where(
            QuoteEstimate.quote_request_id == quote.id,
            QuoteEstimate.quote_request_version == quote.version,
            QuoteEstimate.analysis_run_id == analysis.id,
            QuoteEstimate.pricing_policy_id == policy.id,
            QuoteEstimate.material_rate_id == material.id,
        )
        .options(selectinload(QuoteEstimate.policy))
    )
    created_at = _utc_now(now)
    if existing is not None and _utc_now(existing.expires_at) > created_at:
        return existing

    filament_mg = quote.quantity * sum(
        int(result.filament_mg or 0) for result in analysis.asset_results
    )
    duration_seconds = quote.quantity * sum(
        int(result.duration_seconds or 0) for result in analysis.asset_results
    )
    breakdown = calculate_pricing_v1(
        PricingInputs(
            filament_mg=filament_mg,
            duration_seconds=duration_seconds,
            material_rate_paise_per_gram=material.rate_paise_per_gram,
            machine_rate_paise_per_hour=policy.machine_rate_paise_per_hour,
            setup_fee_paise=policy.setup_fee_paise,
            contingency_bps=policy.contingency_bps,
            minimum_order_paise=policy.minimum_order_paise,
            tax_bps=policy.tax_bps,
        )
    )
    estimated_quote_version = quote.version + 1
    changed = await session.scalar(
        update(QuoteRequest)
        .where(QuoteRequest.id == quote.id, QuoteRequest.version == expected_quote_version)
        .values(version=estimated_quote_version)
        .returning(QuoteRequest.id)
    )
    if changed is None:
        await session.rollback()
        raise PricingConflictError("quote version changed; reload before estimating")
    # Refreshing a price and buyer acceptance share this CAS; no stale issued price can win later.
    await session.execute(
        update(Quote)
        .where(Quote.quote_request_id == quote.id, Quote.status == "issued")
        .values(status="superseded")
    )
    estimate = QuoteEstimate(
        id=uuid4(),
        quote_request_id=quote.id,
        client_token=client_token,
        quote_request_version=estimated_quote_version,
        analysis_run_id=analysis.id,
        pricing_policy_id=policy.id,
        material_rate_id=material.id,
        calculation_version=CALCULATION_VERSION,
        currency="INR",
        material_code=material.code,
        material_name=material.display_name,
        filament_mg=filament_mg,
        duration_seconds=duration_seconds,
        material_rate_paise_per_gram=material.rate_paise_per_gram,
        machine_rate_paise_per_hour=policy.machine_rate_paise_per_hour,
        setup_paise=breakdown.setup_paise,
        contingency_bps=policy.contingency_bps,
        minimum_order_paise=policy.minimum_order_paise,
        tax_bps=policy.tax_bps,
        material_paise=breakdown.material_paise,
        machine_paise=breakdown.machine_paise,
        contingency_paise=breakdown.contingency_paise,
        minimum_adjustment_paise=breakdown.minimum_adjustment_paise,
        pre_tax_paise=breakdown.pre_tax_paise,
        tax_paise=breakdown.tax_paise,
        total_paise=breakdown.total_paise,
        expires_at=created_at + timedelta(hours=policy.estimate_validity_hours),
        created_by_user_id=owner.id if owner is not None else None,
        created_at=created_at,
        updated_at=created_at,
    )
    quote.status = QuoteRequestStatus.ESTIMATE_READY
    quote.version = estimated_quote_version
    quote.updated_at = created_at
    session.add(estimate)
    append_audit_event(
        session,
        AuditEventType.PRICING_ESTIMATE_CREATED,
        occurred_at=created_at,
        actor_user_id=owner.id if owner is not None else None,
        target_user_id=quote.buyer_id,
        request_id=audit_request_id,
        details={
            "quote_request_id": str(quote.id),
            "estimate_id": str(estimate.id),
            "pricing_policy_version": policy.version,
        },
    )
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        repeated = await session.scalar(
            select(QuoteEstimate)
            .where(
                QuoteEstimate.quote_request_id == quote.id,
                QuoteEstimate.client_token == client_token,
            )
            .options(selectinload(QuoteEstimate.policy))
        )
        if repeated is None:
            raise PricingConflictError("estimate inputs changed; reload and retry") from error
        if repeated.analysis_run_id != analysis_run_id or repeated.material_code != material_code:
            raise PricingConflictError(
                "client token was already used for different inputs"
            ) from error
        return repeated
    estimate.policy = policy
    return estimate


async def create_pending_estimates(session: AsyncSession, *, limit: int = 20) -> int:
    """Recoverably calculate first estimates; never issue prices or replace human decisions.

    Scanning persisted successful analysis also recovers a crash after the slice commit.
    The request lock, version CAS and deterministic token make repeated passes harmless.
    """
    candidates = (
        await session.execute(
            select(QuoteRequest.id, QuoteRequest.version, AnalysisRun.id, AnalysisRun.material_code)
            .join(AnalysisRun, AnalysisRun.quote_request_id == QuoteRequest.id)
            .where(
                QuoteRequest.status == QuoteRequestStatus.ANALYSIS_READY,
                QuoteRequest.print_specification.is_not(None),
                AnalysisRun.status == AnalysisRunStatus.SUCCEEDED,
                AnalysisRun.request_version == QuoteRequest.version - 1,
                select(MaterialRate.id)
                .join(PricingPolicy, PricingPolicy.id == MaterialRate.pricing_policy_id)
                .where(
                    PricingPolicy.status == PricingPolicyStatus.ACTIVE,
                    MaterialRate.code == AnalysisRun.material_code,
                )
                .exists(),
            )
            .order_by(AnalysisRun.completed_at, QuoteRequest.id)
            .limit(limit)
        )
    ).all()
    created = 0
    for request_id, version, run_id, material_code in candidates:
        if material_code is None:
            continue
        try:
            await create_quote_estimate(
                session,
                owner=None,
                quote_request_id=request_id,
                client_token=uuid5(NAMESPACE_URL, f"printflow:auto-estimate:{run_id}"),
                expected_quote_version=version,
                analysis_run_id=run_id,
                material_code=material_code,
            )
            created += 1
        except PricingConflictError:
            # Owner action, policy replacement or another worker may win the CAS.
            await session.rollback()
    return created
