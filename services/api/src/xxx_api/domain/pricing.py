"""Pricing states and deterministic money-calculation contracts."""

from dataclasses import dataclass
from enum import StrEnum


class PricingPolicyStatus(StrEnum):
    """Lifecycle for immutable pricing-policy contents."""

    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class PricingInputs:
    """Integer-only inputs for pricing calculation version 1."""

    filament_mg: int
    duration_seconds: int
    material_rate_paise_per_gram: int
    machine_rate_paise_per_hour: int
    setup_fee_paise: int
    contingency_bps: int
    minimum_order_paise: int
    tax_bps: int


@dataclass(frozen=True, slots=True)
class PricingBreakdown:
    """Exact persisted component values produced by pricing version 1."""

    material_paise: int
    machine_paise: int
    setup_paise: int
    contingency_paise: int
    minimum_adjustment_paise: int
    pre_tax_paise: int
    tax_paise: int
    total_paise: int


def _ceil_ratio(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def calculate_pricing_v1(inputs: PricingInputs) -> PricingBreakdown:
    """Calculate an INR estimate without floating-point arithmetic.

    Contingency applies to the subtotal of measured material, machine, and fixed
    setup costs. The minimum is applied before tax. Every fractional paise rounds
    upward so a persisted estimate never understates a configured component.
    """
    values = (
        inputs.filament_mg,
        inputs.duration_seconds,
        inputs.material_rate_paise_per_gram,
        inputs.machine_rate_paise_per_hour,
        inputs.setup_fee_paise,
        inputs.contingency_bps,
        inputs.minimum_order_paise,
        inputs.tax_bps,
    )
    if any(value < 0 for value in values):
        raise ValueError("pricing inputs must be non-negative")
    if inputs.contingency_bps > 10_000 or inputs.tax_bps > 10_000:
        raise ValueError("basis-point inputs cannot exceed 10000")

    material = _ceil_ratio(
        inputs.filament_mg * inputs.material_rate_paise_per_gram,
        1_000,
    )
    machine = _ceil_ratio(
        inputs.duration_seconds * inputs.machine_rate_paise_per_hour,
        3_600,
    )
    subtotal = material + machine + inputs.setup_fee_paise
    contingency = _ceil_ratio(subtotal * inputs.contingency_bps, 10_000)
    before_minimum = subtotal + contingency
    pre_tax = max(before_minimum, inputs.minimum_order_paise)
    minimum_adjustment = pre_tax - before_minimum
    tax = _ceil_ratio(pre_tax * inputs.tax_bps, 10_000)
    return PricingBreakdown(
        material_paise=material,
        machine_paise=machine,
        setup_paise=inputs.setup_fee_paise,
        contingency_paise=contingency,
        minimum_adjustment_paise=minimum_adjustment,
        pre_tax_paise=pre_tax,
        tax_paise=tax,
        total_paise=pre_tax + tax,
    )
