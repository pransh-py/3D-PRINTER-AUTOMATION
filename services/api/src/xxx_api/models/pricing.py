"""Versioned rate cards and immutable quote estimates."""

from __future__ import annotations

from datetime import datetime
from enum import Enum as PythonEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from xxx_api.domain.pricing import PricingPolicyStatus
from xxx_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def enum_values(enum_class: type[PythonEnum]) -> list[str]:
    """Persist stable enum values rather than Python member names."""
    return [str(member.value) for member in enum_class]


class PricingPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable-content version of the owner's rate card."""

    __tablename__ = "pricing_policies"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_pricing_policies_version"),
        CheckConstraint("currency = 'INR'", name="ck_pricing_policies_currency"),
        CheckConstraint(
            "machine_rate_paise_per_hour >= 0",
            name="ck_pricing_policies_machine_rate",
        ),
        CheckConstraint("setup_fee_paise >= 0", name="ck_pricing_policies_setup_fee"),
        CheckConstraint(
            "minimum_order_paise >= 0",
            name="ck_pricing_policies_minimum_order",
        ),
        CheckConstraint(
            "contingency_bps BETWEEN 0 AND 10000",
            name="ck_pricing_policies_contingency",
        ),
        CheckConstraint(
            "tax_bps BETWEEN 0 AND 10000",
            name="ck_pricing_policies_tax",
        ),
        CheckConstraint(
            "estimate_validity_hours BETWEEN 1 AND 720",
            name="ck_pricing_policies_validity",
        ),
        Index("ix_pricing_policies_status", "status"),
        Index(
            "uq_pricing_policies_one_active",
            "status",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )

    version: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    status: Mapped[PricingPolicyStatus] = mapped_column(
        Enum(
            PricingPolicyStatus,
            native_enum=False,
            values_callable=enum_values,
            length=16,
            validate_strings=True,
            create_constraint=True,
            name="ck_pricing_policies_status",
        ),
        default=PricingPolicyStatus.DRAFT,
        server_default=PricingPolicyStatus.DRAFT.value,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), default="INR", server_default="INR")
    machine_rate_paise_per_hour: Mapped[int] = mapped_column(BigInteger, nullable=False)
    setup_fee_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    minimum_order_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    contingency_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    tax_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    estimate_validity_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    activated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    materials: Mapped[list[MaterialRate]] = relationship(
        back_populates="policy",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MaterialRate.code",
    )
    estimates: Mapped[list[QuoteEstimate]] = relationship(back_populates="policy")


class MaterialRate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One material's owner-configured rate within a policy version."""

    __tablename__ = "material_rates"
    __table_args__ = (
        UniqueConstraint("pricing_policy_id", "code", name="uq_material_rates_policy_code"),
        CheckConstraint(
            "rate_paise_per_gram >= 0",
            name="ck_material_rates_rate",
        ),
    )

    pricing_policy_id: Mapped[UUID] = mapped_column(
        ForeignKey("pricing_policies.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    rate_paise_per_gram: Mapped[int] = mapped_column(BigInteger, nullable=False)

    policy: Mapped[PricingPolicy] = relationship(back_populates="materials")
    estimates: Mapped[list[QuoteEstimate]] = relationship(back_populates="material_rate")


class QuoteEstimate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable calculation snapshot for one analyzed quote version."""

    __tablename__ = "quote_estimates"
    __table_args__ = (
        UniqueConstraint(
            "quote_request_id",
            "quote_request_version",
            "pricing_policy_id",
            "material_rate_id",
            name="uq_quote_estimates_inputs",
        ),
        UniqueConstraint(
            "quote_request_id",
            "client_token",
            name="uq_quote_estimates_request_client",
        ),
        CheckConstraint("quote_request_version >= 1", name="ck_quote_estimates_version"),
        CheckConstraint("currency = 'INR'", name="ck_quote_estimates_currency"),
        CheckConstraint("filament_mg >= 0", name="ck_quote_estimates_filament"),
        CheckConstraint("duration_seconds >= 0", name="ck_quote_estimates_duration"),
        CheckConstraint(
            "material_rate_paise_per_gram >= 0",
            name="ck_quote_estimates_material_rate",
        ),
        CheckConstraint(
            "machine_rate_paise_per_hour >= 0",
            name="ck_quote_estimates_machine_rate",
        ),
        CheckConstraint("setup_paise >= 0", name="ck_quote_estimates_setup"),
        CheckConstraint(
            "contingency_bps BETWEEN 0 AND 10000",
            name="ck_quote_estimates_contingency_bps",
        ),
        CheckConstraint(
            "minimum_order_paise >= 0",
            name="ck_quote_estimates_minimum_order",
        ),
        CheckConstraint(
            "tax_bps BETWEEN 0 AND 10000",
            name="ck_quote_estimates_tax_bps",
        ),
        CheckConstraint("material_paise >= 0", name="ck_quote_estimates_material"),
        CheckConstraint("machine_paise >= 0", name="ck_quote_estimates_machine"),
        CheckConstraint(
            "contingency_paise >= 0",
            name="ck_quote_estimates_contingency",
        ),
        CheckConstraint(
            "minimum_adjustment_paise >= 0",
            name="ck_quote_estimates_minimum_adjustment",
        ),
        CheckConstraint("pre_tax_paise >= 0", name="ck_quote_estimates_pre_tax"),
        CheckConstraint("tax_paise >= 0", name="ck_quote_estimates_tax"),
        CheckConstraint("total_paise >= 0", name="ck_quote_estimates_total"),
        Index("ix_quote_estimates_request_created", "quote_request_id", "created_at"),
    )

    quote_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("quote_requests.id", ondelete="RESTRICT"), nullable=False
    )
    client_token: Mapped[UUID] = mapped_column(nullable=False)
    quote_request_version: Mapped[int] = mapped_column(Integer, nullable=False)
    analysis_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="RESTRICT"), nullable=False
    )
    pricing_policy_id: Mapped[UUID] = mapped_column(
        ForeignKey("pricing_policies.id", ondelete="RESTRICT"), nullable=False
    )
    material_rate_id: Mapped[UUID] = mapped_column(
        ForeignKey("material_rates.id", ondelete="RESTRICT"), nullable=False
    )
    calculation_version: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    material_code: Mapped[str] = mapped_column(String(32), nullable=False)
    material_name: Mapped[str] = mapped_column(String(80), nullable=False)
    filament_mg: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False)
    material_rate_paise_per_gram: Mapped[int] = mapped_column(BigInteger, nullable=False)
    machine_rate_paise_per_hour: Mapped[int] = mapped_column(BigInteger, nullable=False)
    setup_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    contingency_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_order_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    material_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    machine_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    contingency_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    minimum_adjustment_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pre_tax_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )

    quote_request: Mapped[QuoteRequest] = relationship(back_populates="estimates")
    policy: Mapped[PricingPolicy] = relationship(back_populates="estimates")
    material_rate: Mapped[MaterialRate] = relationship(back_populates="estimates")


from xxx_api.models.quotes import QuoteRequest  # noqa: E402
