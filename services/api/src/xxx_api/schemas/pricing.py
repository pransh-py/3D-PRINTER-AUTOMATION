"""Strict owner pricing and buyer-safe estimate schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from xxx_api.domain.pricing import PricingPolicyStatus
from xxx_api.schemas.base import UtcSchema


class PricingSchema(UtcSchema):
    """Strict camelCase-compatible schema base."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class MaterialRateInput(PricingSchema):
    """One material rate supplied explicitly by the owner."""

    code: str = Field(min_length=1, max_length=32, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    display_name: str = Field(alias="displayName", min_length=1, max_length=80)
    rate_paise_per_gram: int = Field(alias="ratePaisePerGram", ge=0, le=10_000_000)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("displayName cannot be blank")
        return normalized


class CreatePricingPolicyRequest(PricingSchema):
    """Complete immutable rate-card draft input."""

    machine_rate_paise_per_hour: int = Field(alias="machineRatePaisePerHour", ge=0, le=100_000_000)
    setup_fee_paise: int = Field(alias="setupFeePaise", ge=0, le=100_000_000)
    minimum_order_paise: int = Field(alias="minimumOrderPaise", ge=0, le=100_000_000)
    contingency_bps: int = Field(alias="contingencyBps", ge=0, le=10_000)
    tax_bps: int = Field(alias="taxBps", ge=0, le=10_000)
    estimate_validity_hours: int = Field(alias="estimateValidityHours", ge=1, le=720)
    materials: list[MaterialRateInput] = Field(min_length=1, max_length=50)

    @field_validator("materials")
    @classmethod
    def unique_material_codes(cls, value: list[MaterialRateInput]) -> list[MaterialRateInput]:
        codes = [material.code for material in value]
        if len(codes) != len(set(codes)):
            raise ValueError("material codes must be unique")
        return value


class MaterialRateResponse(PricingSchema):
    """One material rate in an owner-visible policy."""

    id: UUID
    code: str
    display_name: str = Field(alias="displayName")
    rate_paise_per_gram: int = Field(alias="ratePaisePerGram")


class PricingPolicyResponse(PricingSchema):
    """Complete owner-visible pricing-policy version."""

    id: UUID
    version: int
    status: PricingPolicyStatus
    currency: str
    machine_rate_paise_per_hour: int = Field(alias="machineRatePaisePerHour")
    setup_fee_paise: int = Field(alias="setupFeePaise")
    minimum_order_paise: int = Field(alias="minimumOrderPaise")
    contingency_bps: int = Field(alias="contingencyBps")
    tax_bps: int = Field(alias="taxBps")
    estimate_validity_hours: int = Field(alias="estimateValidityHours")
    materials: list[MaterialRateResponse]
    activated_at: datetime | None = Field(alias="activatedAt")
    created_at: datetime = Field(alias="createdAt")


class PricingPolicyListResponse(PricingSchema):
    """Bounded owner policy list."""

    items: list[PricingPolicyResponse]


class CreateQuoteEstimateRequest(PricingSchema):
    """Exact owner-selected inputs for one immutable estimate."""

    client_token: UUID = Field(alias="clientToken")
    expected_quote_version: int = Field(alias="expectedQuoteVersion", ge=1)
    analysis_run_id: UUID = Field(alias="analysisRunId")
    material_code: str = Field(
        alias="materialCode",
        min_length=1,
        max_length=32,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )


class QuoteEstimateResponse(PricingSchema):
    """Buyer-safe immutable estimate breakdown, expressed in paise."""

    id: UUID
    quote_request_version: int = Field(alias="quoteRequestVersion")
    analysis_run_id: UUID = Field(alias="analysisRunId")
    pricing_policy_version: int = Field(alias="pricingPolicyVersion")
    calculation_version: str = Field(alias="calculationVersion")
    currency: str
    material_code: str = Field(alias="materialCode")
    material_name: str = Field(alias="materialName")
    filament_mg: int = Field(alias="filamentMg")
    duration_seconds: int = Field(alias="durationSeconds")
    material_paise: int = Field(alias="materialPaise")
    machine_paise: int = Field(alias="machinePaise")
    setup_paise: int = Field(alias="setupPaise")
    contingency_paise: int = Field(alias="contingencyPaise")
    minimum_adjustment_paise: int = Field(alias="minimumAdjustmentPaise")
    pre_tax_paise: int = Field(alias="preTaxPaise")
    tax_paise: int = Field(alias="taxPaise")
    total_paise: int = Field(alias="totalPaise")
    expires_at: datetime = Field(alias="expiresAt")
    created_at: datetime = Field(alias="createdAt")
