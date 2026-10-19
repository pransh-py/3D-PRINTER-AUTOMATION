"""Owner-only pricing administration and estimate creation adapters."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from xxx_api.dependencies import (
    DatabaseSession,
    OwnerPrincipal,
    RecentMfaOwnerPrincipal,
    SessionCsrf,
    require_trusted_origin,
)
from xxx_api.models.pricing import PricingPolicy, QuoteEstimate
from xxx_api.schemas.pricing import (
    CreatePricingPolicyRequest,
    CreateQuoteEstimateRequest,
    MaterialRateResponse,
    PricingPolicyListResponse,
    PricingPolicyResponse,
    QuoteEstimateResponse,
)
from xxx_api.services.pricing import (
    PricingConflictError,
    PricingNotFoundError,
    activate_pricing_policy,
    create_pricing_policy,
    create_quote_estimate,
    list_pricing_policies,
)

router = APIRouter(prefix="/owner", tags=["owner-pricing"])
TrustedOrigin = Annotated[None, Depends(require_trusted_origin)]


def _request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else None


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _policy_response(policy: PricingPolicy) -> PricingPolicyResponse:
    return PricingPolicyResponse(
        id=policy.id,
        version=policy.version,
        status=policy.status,
        currency=policy.currency,
        machineRatePaisePerHour=policy.machine_rate_paise_per_hour,
        setupFeePaise=policy.setup_fee_paise,
        minimumOrderPaise=policy.minimum_order_paise,
        contingencyBps=policy.contingency_bps,
        taxBps=policy.tax_bps,
        estimateValidityHours=policy.estimate_validity_hours,
        materials=[
            MaterialRateResponse(
                id=material.id,
                code=material.code,
                displayName=material.display_name,
                ratePaisePerGram=material.rate_paise_per_gram,
            )
            for material in policy.materials
        ],
        activatedAt=policy.activated_at,
        createdAt=policy.created_at,
    )


def estimate_response(estimate: QuoteEstimate) -> QuoteEstimateResponse:
    """Map an estimate without exposing internal policy rates or actor IDs."""
    return QuoteEstimateResponse(
        id=estimate.id,
        quoteRequestVersion=estimate.quote_request_version,
        analysisRunId=estimate.analysis_run_id,
        pricingPolicyVersion=estimate.policy.version,
        calculationVersion=estimate.calculation_version,
        currency=estimate.currency,
        materialCode=estimate.material_code,
        materialName=estimate.material_name,
        filamentMg=estimate.filament_mg,
        durationSeconds=estimate.duration_seconds,
        materialPaise=estimate.material_paise,
        machinePaise=estimate.machine_paise,
        setupPaise=estimate.setup_paise,
        contingencyPaise=estimate.contingency_paise,
        minimumAdjustmentPaise=estimate.minimum_adjustment_paise,
        preTaxPaise=estimate.pre_tax_paise,
        taxPaise=estimate.tax_paise,
        totalPaise=estimate.total_paise,
        expiresAt=estimate.expires_at,
        createdAt=estimate.created_at,
    )


@router.get("/pricing-policies", response_model=PricingPolicyListResponse)
async def list_policies(
    response: Response,
    _owner: OwnerPrincipal,
    session: DatabaseSession,
) -> PricingPolicyListResponse:
    """List all pricing versions for the singleton owner."""
    _private(response)
    policies = await list_pricing_policies(session)
    return PricingPolicyListResponse(items=[_policy_response(policy) for policy in policies])


@router.post(
    "/pricing-policies",
    response_model=PricingPolicyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_policy(
    payload: CreatePricingPolicyRequest,
    request: Request,
    response: Response,
    _origin: TrustedOrigin,
    _csrf: SessionCsrf,
    owner: OwnerPrincipal,
    session: DatabaseSession,
) -> PricingPolicyResponse:
    """Create one complete immutable draft pricing version."""
    _private(response)
    try:
        policy = await create_pricing_policy(
            session,
            owner=owner.user,
            machine_rate_paise_per_hour=payload.machine_rate_paise_per_hour,
            setup_fee_paise=payload.setup_fee_paise,
            minimum_order_paise=payload.minimum_order_paise,
            contingency_bps=payload.contingency_bps,
            tax_bps=payload.tax_bps,
            estimate_validity_hours=payload.estimate_validity_hours,
            materials=[
                (material.code, material.display_name, material.rate_paise_per_gram)
                for material in payload.materials
            ],
            audit_request_id=_request_id(request),
        )
    except PricingConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return _policy_response(policy)


@router.post(
    "/pricing-policies/{policy_id}/activate",
    response_model=PricingPolicyResponse,
)
async def activate_policy(
    policy_id: UUID,
    request: Request,
    response: Response,
    _origin: TrustedOrigin,
    _csrf: SessionCsrf,
    owner: RecentMfaOwnerPrincipal,
    session: DatabaseSession,
) -> PricingPolicyResponse:
    """Activate a draft only after recent owner MFA proof."""
    _private(response)
    try:
        policy = await activate_pricing_policy(
            session,
            owner=owner.user,
            policy_id=policy_id,
            audit_request_id=_request_id(request),
        )
    except PricingNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy not found",
        ) from error
    except PricingConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return _policy_response(policy)


@router.post(
    "/quote-requests/{quote_request_id}/estimates",
    response_model=QuoteEstimateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_estimate(
    quote_request_id: UUID,
    payload: CreateQuoteEstimateRequest,
    request: Request,
    response: Response,
    _origin: TrustedOrigin,
    _csrf: SessionCsrf,
    owner: OwnerPrincipal,
    session: DatabaseSession,
) -> QuoteEstimateResponse:
    """Create one immutable estimate from the active policy and sliced evidence."""
    _private(response)
    try:
        estimate = await create_quote_estimate(
            session,
            owner=owner.user,
            quote_request_id=quote_request_id,
            client_token=payload.client_token,
            expected_quote_version=payload.expected_quote_version,
            analysis_run_id=payload.analysis_run_id,
            material_code=payload.material_code,
            audit_request_id=_request_id(request),
        )
    except PricingNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quote or analysis not found",
        ) from error
    except PricingConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return estimate_response(estimate)
