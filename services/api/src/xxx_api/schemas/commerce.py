"""Business operations use exact money, explicit versions and bounded inputs."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, StrictBool, StrictInt, field_validator
from pydantic.alias_generators import to_camel

from xxx_api.schemas.base import UtcSchema


class WorkflowSchema(UtcSchema):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, alias_generator=to_camel, from_attributes=True
    )


class VersionInput(WorkflowSchema):
    expected_version: StrictInt = Field(ge=1)


class IssueQuoteInput(VersionInput):
    estimate_id: UUID
    expires_at: datetime
    adjustment_paise: StrictInt = Field(default=0, ge=-100_000_000, le=100_000_000)
    fulfillment_paise: StrictInt = Field(default=0, ge=0, le=100_000_000)
    reason: str | None = Field(default=None, min_length=1, max_length=2000)

    @field_validator("expires_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Quotation expiry must include a timezone.")
        return value


class RejectInput(VersionInput):
    reason: str = Field(min_length=1, max_length=2000)


class AddressInput(WorkflowSchema):
    recipient_name: str = Field(min_length=1, max_length=100)
    phone_e164: str = Field(pattern=r"^\+91[6-9][0-9]{9}$")
    line1: str = Field(min_length=1, max_length=200)
    line2: str = Field(default="", max_length=200)
    locality: str = Field(min_length=1, max_length=100)
    district: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=1, max_length=100)
    postal_code: str = Field(pattern=r"^[1-9][0-9]{5}$")
    country_code: Literal["IN"] = "IN"


class AcceptQuoteInput(WorkflowSchema):
    address: AddressInput | None = None


class JobActionInput(VersionInput):
    action: Literal[
        "prepare",
        "hold",
        "release",
        "manual_started",
        "print_completed",
        "print_failed",
        "qa_pass",
        "qa_fail",
    ]
    note: str | None = Field(default=None, max_length=2000)


class ReadinessInput(VersionInput):
    bed_clear: StrictBool
    material_loaded: StrictBool
    nozzle_checked: StrictBool
    area_clear: StrictBool
    artifact_reviewed: StrictBool


class DispatchEventInput(WorkflowSchema):
    source_event_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9:_-]+$")
    state: Literal[
        "refused",
        "sent",
        "awaiting_start",
        "printing",
        "completed",
        "needs_attention",
        "cancelled",
        "stopped",
        "resolved",
    ]
    observed_at: datetime
    printer_filename: str | None = Field(
        default=None, pattern=r"^pf_[0-9a-f]{32}_[0-9a-f]{12}\.gcode$"
    )
    dispatch_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    progress_bps: StrictInt | None = Field(default=None, ge=0, le=10000)
    refusal_code: str | None = Field(default=None, max_length=48, pattern=r"^[a-z0-9_]+$")

    @field_validator("observed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("An observation must include its timezone.")
        return value


class FulfillmentInput(VersionInput):
    status: Literal["ready_for_pickup", "out_for_delivery", "shipped", "completed"]
    carrier_name: str | None = Field(default=None, max_length=100)
    tracking_reference: str | None = Field(default=None, max_length=200)


class QuoteOutput(WorkflowSchema):
    id: UUID
    quote_request_id: UUID
    quote_estimate_id: UUID
    version: int
    status: str
    currency: str
    subtotal_paise: int
    adjustment_paise: int
    tax_paise: int
    fulfillment_paise: int
    total_paise: int
    owner_reason: str | None
    print_specification: dict[str, object] | None = None
    issued_at: datetime
    expires_at: datetime
    accepted_at: datetime | None


class OrderOutput(WorkflowSchema):
    id: UUID
    public_reference: str
    accepted_quote_id: UUID
    status: str
    version: int
    currency: str
    amount_paise: int
    accepted_at: datetime
    completed_at: datetime | None
    print_specification: dict[str, object] | None = None


class JobOutput(WorkflowSchema):
    id: UUID
    order_id: UUID
    sequence: int
    status: str
    version: int
    queue_rank: int | None
    attempt_number: int
    queued_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    owner_note: str | None


class FulfillmentOutput(WorkflowSchema):
    mode: str
    status: str
    destination: AddressInput | None = Field(validation_alias="address_snapshot")
    charge_paise: int
    carrier_name: str | None
    tracking_reference: str | None
    dispatched_at: datetime | None
    completed_at: datetime | None
