"""Commercial snapshots, payment evidence and controlled production records."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
    text,
)
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from xxx_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Quote(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint("quote_request_id", "version", name="uq_quotes_request_version"),
        CheckConstraint("version > 0", name="ck_quotes_version"),
        CheckConstraint("currency = 'INR'", name="ck_quotes_currency"),
        CheckConstraint(
            "subtotal_paise >= 0 AND tax_paise >= 0 AND fulfillment_paise >= 0 AND total_paise > 0",
            name="ck_quotes_money",
        ),
        CheckConstraint(
            "total_paise = subtotal_paise + adjustment_paise + tax_paise + fulfillment_paise",
            name="ck_quotes_total",
        ),
        CheckConstraint(
            "status IN ('issued','accepted','rejected','expired','superseded')",
            name="ck_quotes_status",
        ),
        Index(
            "uq_quotes_one_issued",
            "quote_request_id",
            unique=True,
            sqlite_where=text("status = 'issued'"),
            postgresql_where=text("status = 'issued'"),
        ),
        Index(
            "uq_quotes_one_accepted",
            "quote_request_id",
            unique=True,
            sqlite_where=text("status = 'accepted'"),
            postgresql_where=text("status = 'accepted'"),
        ),
    )
    quote_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("quote_requests.id", ondelete="RESTRICT")
    )
    quote_estimate_id: Mapped[UUID] = mapped_column(
        ForeignKey("quote_estimates.id", ondelete="RESTRICT")
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="issued")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    subtotal_paise: Mapped[int] = mapped_column(BigInteger)
    adjustment_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    tax_paise: Mapped[int] = mapped_column(BigInteger)
    fulfillment_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    total_paise: Mapped[int] = mapped_column(BigInteger)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    owner_reason: Mapped[str | None] = mapped_column(Text)
    print_specification: Mapped[dict[str, object] | None] = mapped_column(JSON(none_as_null=True))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuoteLineItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "quote_line_items"
    __table_args__ = (UniqueConstraint("quote_id", "position", name="uq_quote_lines_position"),)
    quote_id: Mapped[UUID] = mapped_column(ForeignKey("quotes.id", ondelete="RESTRICT"))
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(String(200))
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    source_ref: Mapped[dict[str, object] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Order(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("currency = 'INR' AND amount_paise > 0", name="ck_orders_money"),
        CheckConstraint("version > 0", name="ck_orders_version"),
        CheckConstraint(
            "status IN ('payment_pending','payment_processing','paid_confirmed',"
            "'payment_failed','payment_review','payment_rejected','queued','preparing',"
            "'ready_to_print','printing','qa','ready_for_pickup','out_for_delivery',"
            "'shipped','completed','on_hold','print_failed','cancelled',"
            "'refund_pending','refunded')",
            name="ck_orders_status",
        ),
        Index("ix_orders_buyer_created", "buyer_id", "created_at"),
    )
    public_reference: Mapped[str] = mapped_column(String(32), unique=True)
    buyer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    accepted_quote_id: Mapped[UUID] = mapped_column(
        ForeignKey("quotes.id", ondelete="RESTRICT"), unique=True
    )
    status: Mapped[str] = mapped_column(String(32), default="payment_pending")
    version: Mapped[int] = mapped_column(Integer, default=1)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    commercial_snapshot: Mapped[dict[str, object]] = mapped_column(JSON)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def print_specification(self) -> dict[str, object] | None:
        value = self.commercial_snapshot.get("printSpecification")
        return value if isinstance(value, dict) else None


@event.listens_for(Order, "before_update")
def protect_order_snapshot(_mapper: Mapper[Order], _connection: Connection, target: Order) -> None:
    state = inspect(target)
    for field in (
        "public_reference",
        "buyer_id",
        "accepted_quote_id",
        "amount_paise",
        "currency",
        "commercial_snapshot",
        "accepted_at",
    ):
        if state.attrs[field].history.has_changes():
            raise ValueError(f"Accepted order {field} is immutable")


@event.listens_for(Quote, "before_update")
def protect_quote_price(_mapper: Mapper[Quote], _connection: Connection, target: Quote) -> None:
    state = inspect(target)
    for field in (
        "print_specification",
        "quote_request_id",
        "quote_estimate_id",
        "version",
        "currency",
        "subtotal_paise",
        "adjustment_paise",
        "tax_paise",
        "fulfillment_paise",
        "total_paise",
        "owner_id",
        "owner_reason",
        "issued_at",
        "expires_at",
    ):
        if state.attrs[field].history.has_changes():
            raise ValueError(f"Issued quotation {field} is immutable; issue a new version")


def protect_evidence(_mapper: Mapper[Base], _connection: Connection, _target: Base) -> None:
    raise ValueError("Commercial and production evidence is append-only")


class PaymentIntent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payment_intents"
    __table_args__ = (
        UniqueConstraint("order_id", "version", name="uq_payment_intents_order_version"),
        CheckConstraint("amount_paise > 0 AND currency = 'INR'", name="ck_payment_intents_money"),
        CheckConstraint(
            "provider IN ('razorpay','manual_upi')", name="ck_payment_intents_provider"
        ),
        CheckConstraint(
            "status IN ('created','checkout_pending','authorized','captured','failed',"
            "'review','rejected','expired','cancelled')",
            name="ck_payment_intents_status",
        ),
    )
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    provider: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), default="created")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    payment_reference: Mapped[str] = mapped_column(String(64), unique=True)
    provider_order_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    provider_key_id: Mapped[str | None] = mapped_column(String(100))
    checkout_payment_id: Mapped[str | None] = mapped_column(String(100))
    last_reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payment_attempts"
    __table_args__ = (
        CheckConstraint("amount_paise > 0 AND currency = 'INR'", name="ck_payment_attempts_money"),
        CheckConstraint(
            "status IN ('created','authorized','captured','failed','partially_refunded',"
            "'refunded')",
            name="ck_payment_attempts_status",
        ),
    )
    payment_intent_id: Mapped[UUID] = mapped_column(
        ForeignKey("payment_intents.id", ondelete="RESTRICT")
    )
    provider_payment_id: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(24))
    currency: Mapped[str] = mapped_column(String(3))
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    method_category: Mapped[str | None] = mapped_column(String(40))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentProviderEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payment_provider_events"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_payment_events_provider_id"),
        CheckConstraint("provider = 'razorpay'", name="ck_payment_events_provider"),
        CheckConstraint(
            "(evidence_source = 'webhook' AND signature_validated_at IS NOT NULL "
            "AND api_authenticated_at IS NULL) OR (evidence_source = 'api' "
            "AND api_authenticated_at IS NOT NULL AND signature_validated_at IS NULL)",
            name="ck_payment_events_authentication",
        ),
        CheckConstraint(
            "status IN ('received','processed','ignored','failed')", name="ck_payment_events_status"
        ),
    )
    provider: Mapped[str] = mapped_column(String(24))
    provider_event_id: Mapped[str] = mapped_column(String(120))
    event_type: Mapped[str] = mapped_column(String(80))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    evidence_source: Mapped[str] = mapped_column(
        String(16), default="webhook", server_default="webhook"
    )
    signature_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    api_authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_intent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("payment_intents.id", ondelete="RESTRICT")
    )
    payment_attempt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("payment_attempts.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(16), default="received")
    failure_code: Mapped[str | None] = mapped_column(String(80))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PrintJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "print_jobs"
    __table_args__ = (
        UniqueConstraint("order_id", "sequence", name="uq_print_jobs_order_sequence"),
        CheckConstraint(
            "sequence > 0 AND attempt_number > 0 AND version > 0", name="ck_print_jobs_numbers"
        ),
        CheckConstraint(
            "status IN ('queued','on_hold','preparing','ready_to_print','authorized',"
            "'claimed','printing','qa','completed','failed','cancelled')",
            name="ck_print_jobs_status",
        ),
        Index("ix_print_jobs_queue", "status", "queue_rank"),
    )
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    sequence: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="queued")
    version: Mapped[int] = mapped_column(Integer, default=1)
    queue_rank: Mapped[int | None] = mapped_column(BigInteger)
    printer_id: Mapped[UUID | None] = mapped_column(ForeignKey("printers.id", ondelete="RESTRICT"))
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    failure_code: Mapped[str | None] = mapped_column(String(64))
    owner_note: Mapped[str | None] = mapped_column(Text)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PrintJobItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "print_job_items"
    __table_args__ = (
        UniqueConstraint("print_job_id", "position", name="uq_print_items_position"),
        CheckConstraint("quantity > 0 AND position > 0", name="ck_print_items_numbers"),
    )
    print_job_id: Mapped[UUID] = mapped_column(ForeignKey("print_jobs.id", ondelete="RESTRICT"))
    analysis_asset_result_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_asset_results.id", ondelete="RESTRICT")
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    artifact_storage_key: Mapped[str] = mapped_column(String(512))
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    position: Mapped[int] = mapped_column(Integer)


class Printer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "printers"
    __table_args__ = (
        CheckConstraint("code = 'ad5x'", name="ck_printers_single_code"),
        CheckConstraint(
            "state IN ('unknown','offline','idle','busy','paused','error','maintenance')",
            name="ck_printers_state",
        ),
    )
    code: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(64))
    firmware_version: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), default="unknown")
    active_job_id: Mapped[UUID | None] = mapped_column()
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BridgeInstallation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bridge_installations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_pairing','paired','revoked')", name="ck_bridges_status"
        ),
    )
    printer_id: Mapped[UUID] = mapped_column(
        ForeignKey("printers.id", ondelete="RESTRICT"), unique=True
    )
    status: Mapped[str] = mapped_column(String(24), default="pending_pairing")
    installation_name: Mapped[str] = mapped_column(String(100))
    bridge_version: Mapped[str] = mapped_column(String(64), default="1")
    adapter_name: Mapped[str] = mapped_column(String(64), default="manual-orca")
    credential_digest: Mapped[str] = mapped_column(String(64), unique=True)
    pairing_digest: Mapped[str | None] = mapped_column(String(64), unique=True)
    pairing_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paired_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    paired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PrintReadinessCheck(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "print_readiness_checks"
    print_job_id: Mapped[UUID] = mapped_column(ForeignKey("print_jobs.id", ondelete="RESTRICT"))
    printer_id: Mapped[UUID | None] = mapped_column(ForeignKey("printers.id", ondelete="RESTRICT"))
    completed_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    checklist_version: Mapped[str] = mapped_column(String(32), default="manual-orca/1")
    checklist_snapshot: Mapped[dict[str, object]] = mapped_column(JSON)
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PrintAuthorization(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "print_authorizations"
    __table_args__ = (
        Index(
            "uq_authorizations_live_job",
            "print_job_id",
            unique=True,
            sqlite_where=text("revoked_at IS NULL AND consumed_at IS NULL"),
            postgresql_where=text("revoked_at IS NULL AND consumed_at IS NULL"),
        ),
    )
    print_job_id: Mapped[UUID] = mapped_column(ForeignKey("print_jobs.id", ondelete="RESTRICT"))
    printer_id: Mapped[UUID] = mapped_column(ForeignKey("printers.id", ondelete="RESTRICT"))
    bridge_installation_id: Mapped[UUID] = mapped_column(
        ForeignKey("bridge_installations.id", ondelete="RESTRICT")
    )
    readiness_check_id: Mapped[UUID] = mapped_column(
        ForeignKey("print_readiness_checks.id", ondelete="RESTRICT")
    )
    nonce_digest: Mapped[str] = mapped_column(String(64), unique=True)
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    issued_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_code: Mapped[str | None] = mapped_column(String(64))


class PrintJobEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "print_job_events"
    __table_args__ = (
        UniqueConstraint("print_job_id", "source_event_id", name="uq_job_events_source"),
    )
    print_job_id: Mapped[UUID] = mapped_column(ForeignKey("print_jobs.id", ondelete="RESTRICT"))
    event_type: Mapped[str] = mapped_column(String(64))
    source_event_id: Mapped[str] = mapped_column(String(128))
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    bridge_installation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("bridge_installations.id", ondelete="RESTRICT")
    )
    progress_bps: Mapped[int | None] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)


class Fulfillment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "fulfillments"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('pickup','local_delivery','shipping')", name="ck_fulfillments_mode"
        ),
        CheckConstraint(
            "status IN ('pending','ready_for_pickup','out_for_delivery','shipped',"
            "'delivered','completed','failed','returned')",
            name="ck_fulfillments_status",
        ),
        CheckConstraint("charge_paise >= 0", name="ck_fulfillments_charge"),
    )
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), unique=True
    )
    mode: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    address_snapshot: Mapped[dict[str, object] | None] = mapped_column(JSON)
    carrier_name: Mapped[str | None] = mapped_column(String(100))
    tracking_reference: Mapped[str | None] = mapped_column(String(200))
    charge_paise: Mapped[int] = mapped_column(BigInteger)
    prepared_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


for evidence_model in (QuoteLineItem, PrintJobItem, PrintReadinessCheck, PrintJobEvent):
    event.listen(evidence_model, "before_update", protect_evidence)
    event.listen(evidence_model, "before_delete", protect_evidence)


@event.listens_for(PaymentProviderEvent, "before_update")
def protect_payment_event(
    _mapper: Mapper[PaymentProviderEvent], _connection: Connection, target: PaymentProviderEvent
) -> None:
    state = inspect(target)
    for field in (
        "provider",
        "provider_event_id",
        "event_type",
        "payload_sha256",
        "evidence_source",
        "signature_validated_at",
        "api_authenticated_at",
        "received_at",
    ):
        if state.attrs[field].history.has_changes():
            raise ValueError("Provider validation evidence is immutable")
    for field in ("payment_intent_id", "payment_attempt_id"):
        history = state.attrs[field].history
        if history.has_changes() and history.deleted and history.deleted[0] is not None:
            raise ValueError("Correlated provider evidence cannot be rebound")


@event.listens_for(PaymentIntent, "before_update")
def protect_payment_binding(
    _mapper: Mapper[PaymentIntent], _connection: Connection, target: PaymentIntent
) -> None:
    state = inspect(target)
    for field in (
        "order_id",
        "version",
        "provider",
        "currency",
        "amount_paise",
        "payment_reference",
        "provider_key_id",
    ):
        if state.attrs[field].history.has_changes():
            raise ValueError("Payment instruction is immutable")
    history = state.attrs.provider_order_id.history
    if history.has_changes() and history.deleted and history.deleted[0] is not None:
        raise ValueError("Bound provider order cannot be replaced")


event.listen(PaymentProviderEvent, "before_delete", protect_evidence)
event.listen(PaymentIntent, "before_delete", protect_evidence)
event.listen(PaymentAttempt, "before_delete", protect_evidence)
event.listen(PaymentAttempt, "before_update", protect_evidence)
