"""Transactional quotation, order and production transitions."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from json import dumps
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from xxx_api.domain.auth import AuditEventType
from xxx_api.domain.quotes import (
    AnalysisAssetStatus,
    AnalysisRunStatus,
    ModelAssetStatus,
    QuoteRequestStatus,
)
from xxx_api.domain.roles import Role
from xxx_api.models.analysis import AnalysisAssetResult, AnalysisRun, OutboxEvent
from xxx_api.models.commerce import (
    Fulfillment,
    Order,
    PaymentAttempt,
    PaymentIntent,
    PaymentProviderEvent,
    Printer,
    PrintJob,
    PrintJobEvent,
    PrintJobItem,
    PrintReadinessCheck,
    Quote,
    QuoteLineItem,
)
from xxx_api.models.identity import User
from xxx_api.models.pricing import QuoteEstimate
from xxx_api.models.quotes import ModelAsset, QuoteRequest
from xxx_api.services.audit import append_audit_event
from xxx_api.services.notifications import request_notice


class WorkflowConflictError(Exception):
    """A stale input or unmet precondition prevents a business transition."""


class WorkflowNotFoundError(Exception):
    """The resource is absent or concealed by ownership."""


def utc(value: datetime | None = None) -> datetime:
    result = value or datetime.now(UTC)
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


def require_owner(user: User) -> None:
    if user.role is not Role.OWNER or user.owner_slot != "primary":
        raise WorkflowNotFoundError


async def compare_version(
    session: AsyncSession,
    model: type[Order] | type[PrintJob] | type[QuoteRequest],
    row: Order | PrintJob | QuoteRequest,
    expected_version: int,
) -> None:
    # A database CAS works on SQLite labs as well as PostgreSQL. SELECT FOR UPDATE alone does not.
    changed = await session.scalar(
        update(model)
        .where(model.id == row.id, model.version == expected_version)
        .values(version=expected_version + 1)
        .returning(model.id)
    )
    if changed is None:
        await session.rollback()
        raise WorkflowConflictError("This record changed. Refresh before trying again.")


def audit(
    session: AsyncSession,
    event: AuditEventType,
    user: User | None,
    target_id: UUID,
    details: dict[str, object] | None = None,
) -> None:
    append_audit_event(
        session,
        event,
        occurred_at=utc(),
        actor_user_id=user.id if user else None,
        details={"target_id": str(target_id), **(details or {})},
    )


async def get_order(session: AsyncSession, *, user: User, order_id: UUID) -> Order:
    filters = [Order.id == order_id]
    if user.role is not Role.OWNER:
        filters.append(Order.buyer_id == user.id)
    order = await session.scalar(select(Order).where(*filters))
    if order is None:
        raise WorkflowNotFoundError
    return order


async def visible_quote(session: AsyncSession, user: User, quote_id: UUID) -> Quote:
    statement = select(Quote).join(QuoteRequest).where(Quote.id == quote_id)
    if user.role is not Role.OWNER:
        statement = statement.where(QuoteRequest.buyer_id == user.id)
    quote = await session.scalar(statement)
    if quote is None:
        raise WorkflowNotFoundError
    return quote


async def retry_slicing(
    session: AsyncSession, owner: User, request_id: UUID, expected_version: int
) -> AnalysisRun:
    require_owner(owner)
    request = await session.get(QuoteRequest, request_id)
    if request is None:
        raise WorkflowNotFoundError
    previous = await session.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.quote_request_id == request_id)
        .order_by(AnalysisRun.request_version.desc())
    )
    if (
        request.status
        not in {QuoteRequestStatus.ANALYSIS_READY, QuoteRequestStatus.ANALYSIS_FAILED}
        or previous is None
        or not (
            previous.status is AnalysisRunStatus.AWAITING_PROFILE
            or (
                previous.status is AnalysisRunStatus.FAILED
                and (previous.failure_code or "").startswith("slicer_")
            )
        )
    ):
        raise WorkflowConflictError(
            "Only waiting-profile or slicer-failed requests can be retried."
        )
    assets = list(
        await session.scalars(select(ModelAsset).where(ModelAsset.quote_request_id == request_id))
    )
    if not assets or any(
        asset.status is ModelAssetStatus.REJECTED
        and not (asset.rejection_code or "").startswith("slicer_")
        for asset in assets
    ):
        raise WorkflowConflictError(
            "Invalid source models cannot be re-enabled by a slicing retry."
        )
    await compare_version(session, QuoteRequest, request, expected_version)
    request.status = QuoteRequestStatus.ANALYZING
    for asset in assets:
        asset.status = ModelAssetStatus.QUARANTINED
        asset.rejection_code = None
    run = AnalysisRun(
        id=uuid4(),
        quote_request_id=request.id,
        request_version=request.version,
        status=AnalysisRunStatus.QUEUED,
        attempt_count=0,
        validator_version="xxx-model-validator/1",
        queued_at=utc(),
    )
    session.add(run)
    session.add(
        OutboxEvent(
            topic="analysis.requested",
            aggregate_type="analysis_run",
            aggregate_id=run.id,
            idempotency_key=f"analysis:{run.id}",
            payload={
                "analysis_run_id": str(run.id),
                "quote_request_id": str(request.id),
                "request_version": request.version,
            },
            available_at=utc(),
            attempt_count=0,
        )
    )
    audit(
        session,
        AuditEventType.ANALYSIS_RUN_QUEUED,
        owner,
        run.id,
        {"reason": "owner_slicing_retry"},
    )
    await session.commit()
    return run


async def issue_quote(
    session: AsyncSession,
    *,
    owner: User,
    request_id: UUID,
    estimate_id: UUID,
    expected_version: int,
    expires_at: datetime,
    adjustment_paise: int = 0,
    fulfillment_paise: int = 0,
    reason: str | None = None,
) -> Quote:
    require_owner(owner)
    now = utc()
    expiry = utc(expires_at)
    if not now < expiry <= now + timedelta(days=30):
        raise WorkflowConflictError("Quotation expiry must be in the next 30 days.")
    if adjustment_paise and not (reason or "").strip():
        raise WorkflowConflictError("A price adjustment requires a reason.")
    request = await session.get(QuoteRequest, request_id)
    estimate = await session.get(QuoteEstimate, estimate_id)
    if request is None or estimate is None or estimate.quote_request_id != request_id:
        raise WorkflowNotFoundError
    if request.status not in {
        QuoteRequestStatus.ESTIMATE_READY,
        QuoteRequestStatus.OWNER_REVIEW,
        QuoteRequestStatus.QUOTED,
    }:
        raise WorkflowConflictError("A current estimate is required before issuing a quotation.")
    if request.print_specification:
        analysis = await session.get(AnalysisRun, estimate.analysis_run_id)
        specification = request.print_specification
        if (
            analysis is None
            or analysis.status is not AnalysisRunStatus.SUCCEEDED
            or analysis.profile_sha256 != specification.get("profileSha256")
            or analysis.material_code != specification.get("materialCode")
            or analysis.print_preset_code != specification.get("presetCode")
            or estimate.material_code != specification.get("materialCode")
        ):
            raise WorkflowConflictError(
                "The sliced result does not match the selected print preset."
            )
    if utc(estimate.expires_at) <= now:
        raise WorkflowConflictError("The estimate has expired. Create a fresh estimate.")
    if estimate.quote_request_version != request.version:
        # Reissuing an unchanged, still-current quotation is allowed; an older estimate is not.
        current = await session.scalar(
            select(Quote).where(Quote.quote_request_id == request_id, Quote.status == "issued")
        )
        if current is None or current.quote_estimate_id != estimate_id:
            raise WorkflowConflictError("The estimate no longer matches this request.")
    accepted = await session.scalar(
        select(Quote.id).where(Quote.quote_request_id == request_id, Quote.status == "accepted")
    )
    if accepted:
        raise WorkflowConflictError("An accepted quotation cannot be replaced.")
    subtotal = estimate.pre_tax_paise
    taxable = subtotal + adjustment_paise
    if taxable < 0 or fulfillment_paise < 0:
        raise WorkflowConflictError("Quotation components cannot create a negative subtotal.")
    tax = (taxable * estimate.tax_bps + 9999) // 10000
    total = taxable + tax + fulfillment_paise
    if total <= 0:
        raise WorkflowConflictError("The final quotation must have a positive total.")
    await compare_version(session, QuoteRequest, request, expected_version)
    await session.execute(
        update(Quote)
        .where(Quote.quote_request_id == request_id, Quote.status == "issued")
        .values(status="superseded")
    )
    version = (
        await session.scalar(
            select(func.max(Quote.version)).where(Quote.quote_request_id == request_id)
        )
        or 0
    ) + 1
    quote = Quote(
        id=uuid4(),
        quote_request_id=request_id,
        quote_estimate_id=estimate_id,
        version=version,
        status="issued",
        currency="INR",
        subtotal_paise=subtotal,
        adjustment_paise=adjustment_paise,
        tax_paise=tax,
        fulfillment_paise=fulfillment_paise,
        total_paise=total,
        owner_id=owner.id,
        owner_reason=(reason or "").strip() or None,
        print_specification=deepcopy(request.print_specification),
        issued_at=now,
        expires_at=expiry,
    )
    session.add(quote)
    await session.flush()
    components = [
        ("material", "Material", estimate.material_paise),
        ("machine", "Print time", estimate.machine_paise),
        ("setup", "Setup", estimate.setup_paise),
        ("contingency", "Contingency", estimate.contingency_paise),
        ("minimum_adjustment", "Minimum order adjustment", estimate.minimum_adjustment_paise),
        ("owner_adjustment", "Owner adjustment", adjustment_paise),
        ("tax", "Tax", tax),
        ("fulfillment", "Fulfilment", fulfillment_paise),
    ]
    for position, (kind, description, amount) in enumerate(components, start=1):
        session.add(
            QuoteLineItem(
                quote_id=quote.id,
                position=position,
                kind=kind,
                description=description,
                amount_paise=amount,
                source_ref={"estimateId": str(estimate.id)},
                created_at=now,
            )
        )
    request.status = QuoteRequestStatus.QUOTED
    audit(session, AuditEventType.QUOTE_ISSUED, owner, quote.id, {"version": version})
    await request_notice(session, "buyer.quote_issued", "quote", quote.id, request.buyer_id)
    await session.commit()
    return quote


async def reject_request(
    session: AsyncSession, *, owner: User, request_id: UUID, expected_version: int, reason: str
) -> QuoteRequest:
    require_owner(owner)
    if not reason.strip():
        raise WorkflowConflictError("A rejection requires a reason.")
    request = await session.get(QuoteRequest, request_id)
    if request is None:
        raise WorkflowNotFoundError
    if request.status not in {
        QuoteRequestStatus.ANALYSIS_READY,
        QuoteRequestStatus.ANALYSIS_FAILED,
        QuoteRequestStatus.ESTIMATE_READY,
        QuoteRequestStatus.OWNER_REVIEW,
        QuoteRequestStatus.QUOTED,
    }:
        raise WorkflowConflictError("This request cannot be rejected in its current state.")
    if await session.scalar(
        select(Quote.id).where(Quote.quote_request_id == request_id, Quote.status == "accepted")
    ):
        raise WorkflowConflictError("An accepted order cannot be rejected as a request.")
    await compare_version(session, QuoteRequest, request, expected_version)
    await session.execute(
        update(Quote)
        .where(Quote.quote_request_id == request_id, Quote.status == "issued")
        .values(status="rejected")
    )
    request.status = QuoteRequestStatus.REJECTED
    request.owner_rejection_reason = reason.strip()
    audit(session, AuditEventType.QUOTE_REJECTED, owner, request.id, {"reason": reason.strip()})
    await request_notice(
        session, "buyer.request_rejected", "quote_request", request.id, request.buyer_id
    )
    await session.commit()
    return request


async def accept_quote(
    session: AsyncSession,
    *,
    buyer: User,
    quote_id: UUID,
    address: dict[str, object] | None = None,
    now: datetime | None = None,
) -> Order:
    if buyer.role is not Role.BUYER or buyer.email_verified_at is None:
        raise WorkflowNotFoundError
    quote = await visible_quote(session, buyer, quote_id)
    existing = await session.scalar(select(Order).where(Order.accepted_quote_id == quote_id))
    if existing:
        fulfillment = await session.scalar(
            select(Fulfillment).where(Fulfillment.order_id == existing.id)
        )
        if fulfillment is None or fulfillment.address_snapshot != address:
            raise WorkflowConflictError("This quotation was already accepted with another address.")
        return existing
    accepted_at = utc(now)
    if quote.status != "issued" or utc(quote.expires_at) <= accepted_at:
        raise WorkflowConflictError("Only a current, unexpired quotation can be accepted.")
    request = await session.get(QuoteRequest, quote.quote_request_id)
    estimate = await session.get(QuoteEstimate, quote.quote_estimate_id)
    assert request is not None and estimate is not None
    if request.fulfillment_mode != "pickup" and not address:
        raise WorkflowConflictError("Delivery and shipping require a destination address.")
    if request.fulfillment_mode == "pickup" and address:
        raise WorkflowConflictError("Omit destination details for a pickup order.")
    # Acceptance, rejection and reissuance share the request CAS, not separate quote-only locks.
    await compare_version(session, QuoteRequest, request, request.version)
    changed = await session.scalar(
        update(Quote)
        .where(Quote.id == quote_id, Quote.status == "issued")
        .values(status="accepted", accepted_at=accepted_at)
        .returning(Quote.id)
    )
    if changed is None:
        await session.rollback()
        raise WorkflowConflictError("Quotation acceptance is already in progress. Refresh.")
    results = list(
        await session.scalars(
            select(AnalysisAssetResult)
            .where(AnalysisAssetResult.analysis_run_id == estimate.analysis_run_id)
            .order_by(AnalysisAssetResult.id)
        )
    )
    if not results or any(
        result.status is not AnalysisAssetStatus.SLICED
        or not result.artifact_sha256
        or not result.artifact_storage_key
        for result in results
    ):
        await session.rollback()
        raise WorkflowConflictError("The approved sliced artifacts are missing.")
    lines = list(
        await session.scalars(
            select(QuoteLineItem)
            .where(QuoteLineItem.quote_id == quote_id)
            .order_by(QuoteLineItem.position)
        )
    )
    if sum(line.amount_paise for line in lines) != quote.total_paise:
        await session.rollback()
        raise WorkflowConflictError("The quotation line items do not reconcile.")
    analysis = await session.get(AnalysisRun, estimate.analysis_run_id)
    if analysis is None or analysis.status is not AnalysisRunStatus.SUCCEEDED:
        await session.rollback()
        raise WorkflowConflictError("The approved analysis is no longer available.")
    if (
        quote.print_specification != request.print_specification
        or (
            quote.print_specification
            and (
                analysis.profile_sha256 != quote.print_specification.get("profileSha256")
                or analysis.material_code != quote.print_specification.get("materialCode")
                or analysis.print_preset_code != quote.print_specification.get("presetCode")
            )
        )
    ):
        await session.rollback()
        raise WorkflowConflictError(
            "The quotation no longer matches the selected print specification."
        )
    snapshot: dict[str, object] = {
        "schemaVersion": 2,
        "printSpecification": deepcopy(quote.print_specification),
        "quoteId": str(quote.id),
        "quoteVersion": quote.version,
        "quoteRequestId": str(request.id),
        "estimateId": str(estimate.id),
        "analysisRunId": str(estimate.analysis_run_id),
        "pricingPolicyId": str(estimate.pricing_policy_id),
        "materialCode": estimate.material_code,
        "profileSha256": analysis.profile_sha256,
        "currency": "INR",
        "totalPaise": quote.total_paise,
        "fulfillmentMode": request.fulfillment_mode,
        "fulfillmentPaise": quote.fulfillment_paise,
        "quantity": request.quantity,
        "lines": [
            {"kind": line.kind, "description": line.description, "amountPaise": line.amount_paise}
            for line in lines
        ],
        "artifacts": [
            {
                "resultId": str(result.id),
                "sha256": result.artifact_sha256,
                "storageKey": result.artifact_storage_key,
                "quantity": request.quantity,
            }
            for result in results
        ],
    }
    order = Order(
        id=uuid4(),
        public_reference=f"PF-{uuid4().hex[:16].upper()}",
        buyer_id=buyer.id,
        accepted_quote_id=quote.id,
        status="payment_pending",
        version=1,
        currency="INR",
        amount_paise=quote.total_paise,
        commercial_snapshot=snapshot,
        accepted_at=accepted_at,
    )
    session.add(order)
    await session.flush()
    session.add(
        Fulfillment(
            order_id=order.id,
            mode=request.fulfillment_mode,
            status="pending",
            charge_paise=quote.fulfillment_paise,
            address_snapshot=address,
        )
    )
    audit(session, AuditEventType.QUOTE_ACCEPTED, buyer, order.id, {"quote_id": str(quote.id)})
    await request_notice(session, "buyer.order_accepted", "order", order.id, buyer.id)
    await request_notice(session, "owner.quote_accepted", "order", order.id)
    await session.commit()
    return order


async def record_captured_payment(
    session: AsyncSession,
    *,
    event_id: UUID,
    intent_id: UUID,
    provider_order_id: str,
    provider_payment_id: str,
    amount_paise: int,
    currency: str,
    captured: bool,
) -> Order:
    """Internal adapter boundary; never exposed as a buyer/owner 'mark paid' route.

    The gateway adapter persists signed webhook or authenticated API evidence first.
    A callback/authorized/unknown/mismatched event cannot create the business effect.
    """
    event = await session.get(PaymentProviderEvent, event_id)
    intent = await session.get(PaymentIntent, intent_id)
    if event is None or intent is None:
        raise WorkflowNotFoundError
    order = await session.get(Order, intent.order_id)
    assert order is not None
    if (
        not (
            (
                event.evidence_source == "webhook"
                and event.signature_validated_at is not None
                and event.event_type in {"payment.captured", "order.paid"}
            )
            or (
                event.evidence_source == "api"
                and event.api_authenticated_at is not None
                and event.event_type == "api.reconciled"
            )
        )
        or event.provider != "razorpay"
        or event.status not in {"received", "processed"}
        or not captured
        or intent.provider != "razorpay"
        or intent.provider_order_id != provider_order_id
        or amount_paise != intent.amount_paise
        or amount_paise != order.amount_paise
        or currency != "INR"
        or currency != intent.currency
        or not provider_payment_id
        or len(provider_payment_id) > 100
    ):
        raise WorkflowConflictError("Payment evidence does not match the accepted order.")
    if event.payment_intent_id not in {None, intent.id}:
        raise WorkflowConflictError("The provider event belongs to another payment.")
    previous = await session.scalar(
        select(PaymentAttempt).where(PaymentAttempt.provider_payment_id == provider_payment_id)
    )
    if previous:
        if previous.payment_intent_id != intent.id or previous.status != "captured":
            raise WorkflowConflictError("The provider payment belongs to another intent.")
        event.status = "processed"
        event.payment_intent_id = intent.id
        event.payment_attempt_id = previous.id
        event.processed_at = utc()
        await session.commit()
        return order
    if intent.status == "captured" or order.status not in {
        "payment_pending",
        "payment_processing",
        "payment_failed",
        "payment_review",
    }:
        raise WorkflowConflictError("The order already has a payment or cannot be paid.")
    await compare_version(session, Order, order, order.version)
    now = utc()
    attempt = PaymentAttempt(
        id=uuid4(),
        payment_intent_id=intent.id,
        provider_payment_id=provider_payment_id,
        status="captured",
        currency=currency,
        amount_paise=amount_paise,
        captured_at=now,
    )
    session.add(attempt)
    await session.flush()
    intent.status = "captured"
    order.status = "paid_confirmed"
    event.payment_intent_id = intent.id
    event.payment_attempt_id = attempt.id
    event.status = "processed"
    event.processed_at = now
    session.add(
        OutboxEvent(
            topic="production.requested",
            aggregate_type="order",
            aggregate_id=order.id,
            idempotency_key=f"production:{order.id}:1",
            payload={"schemaVersion": 1, "orderId": str(order.id)},
            available_at=now,
            attempt_count=0,
        )
    )
    audit(
        session,
        AuditEventType.PAYMENT_CONFIRMED,
        None,
        order.id,
        {"attempt_id": str(attempt.id), "event_id": str(event.id)},
    )
    await request_notice(session, "buyer.payment_confirmed", "order", order.id, order.buyer_id)
    await request_notice(session, "owner.payment_confirmed", "order", order.id)
    await session.commit()
    return order


async def enqueue_paid_orders(session: AsyncSession, *, limit: int = 20) -> int:
    """Consume the database outbox transactionally; duplicate deliveries reuse one job."""
    events = list(
        await session.scalars(
            select(OutboxEvent)
            .where(
                OutboxEvent.topic == "production.requested",
                OutboxEvent.published_at.is_(None),
                OutboxEvent.available_at <= utc(),
            )
            .order_by(OutboxEvent.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    count = 0
    for event in events:
        order = await session.get(Order, event.aggregate_id)
        if order is None:
            raise WorkflowConflictError("Production outbox order is missing.")
        existing = await session.scalar(
            select(PrintJob).where(PrintJob.order_id == order.id, PrintJob.sequence == 1)
        )
        if existing:
            event.published_at = utc()
            continue
        if order.status != "paid_confirmed":
            raise WorkflowConflictError("Only a confirmed paid order may enter the queue.")
        await compare_version(session, Order, order, order.version)
        raw_artifacts = order.commercial_snapshot.get("artifacts")
        if not isinstance(raw_artifacts, list) or not raw_artifacts:
            raise WorkflowConflictError("The accepted artifact manifest is missing.")
        now = utc()
        job = PrintJob(
            id=uuid4(),
            order_id=order.id,
            sequence=1,
            status="queued",
            version=1,
            attempt_number=1,
            queue_rank=int(now.timestamp() * 1_000_000),
            queued_at=now,
        )
        session.add(job)
        await session.flush()
        for position, artifact in enumerate(raw_artifacts, start=1):
            if not isinstance(artifact, dict):
                raise WorkflowConflictError("The accepted artifact manifest is invalid.")
            result = await session.get(AnalysisAssetResult, UUID(str(artifact["resultId"])))
            if (
                result is None
                or result.artifact_sha256 != artifact["sha256"]
                or result.artifact_storage_key != artifact["storageKey"]
            ):
                raise WorkflowConflictError("An accepted sliced artifact changed.")
            session.add(
                PrintJobItem(
                    print_job_id=job.id,
                    analysis_asset_result_id=result.id,
                    quantity=int(artifact["quantity"]),
                    artifact_storage_key=str(artifact["storageKey"]),
                    artifact_sha256=str(artifact["sha256"]),
                    position=position,
                )
            )
        order.status = "queued"
        await request_notice(session, "buyer.order_updated", "order", order.id, order.buyer_id)
        event.published_at = now
        event.attempt_count += 1
        count += 1
    await session.commit()
    return count


async def manifest(session: AsyncSession, job: PrintJob) -> tuple[list[PrintJobItem], str]:
    items = list(
        await session.scalars(
            select(PrintJobItem)
            .where(PrintJobItem.print_job_id == job.id)
            .order_by(PrintJobItem.position)
        )
    )
    if not items:
        raise WorkflowConflictError("This job has no approved artifacts.")
    for item in items:
        result = await session.get(AnalysisAssetResult, item.analysis_asset_result_id)
        if (
            result is None
            or result.status is not AnalysisAssetStatus.SLICED
            or (
                item.artifact_sha256 != result.artifact_sha256
                or item.artifact_storage_key != result.artifact_storage_key
            )
        ):
            raise WorkflowConflictError("The production artifact no longer matches its analysis.")
    encoded = dumps(
        [
            {
                "position": item.position,
                "sha256": item.artifact_sha256,
                "quantity": item.quantity,
                "resultId": str(item.analysis_asset_result_id),
            }
            for item in items
        ],
        sort_keys=True,
        separators=(",", ":"),
    )
    return items, sha256(encoded.encode()).hexdigest()


JOB_ACTIONS: dict[str, tuple[set[str], str, str]] = {
    "prepare": ({"queued"}, "preparing", "preparing"),
    "hold": ({"queued", "preparing", "ready_to_print"}, "on_hold", "on_hold"),
    "release": ({"on_hold"}, "queued", "queued"),
    "manual_started": ({"ready_to_print"}, "printing", "printing"),
    "print_completed": ({"printing"}, "qa", "qa"),
    "print_failed": ({"printing"}, "failed", "print_failed"),
    "qa_pass": ({"qa"}, "completed", "qa"),
    "qa_fail": ({"qa"}, "failed", "print_failed"),
}


async def singleton_printer(session: AsyncSession) -> Printer:
    printer = await session.scalar(select(Printer).where(Printer.code == "ad5x"))
    if printer is not None:
        return printer
    try:
        async with session.begin_nested():
            printer = Printer(
                code="ad5x", display_name="AD5X", model="FlashForge AD5X", state="unknown"
            )
            session.add(printer)
            await session.flush()
    except IntegrityError:
        printer = await session.scalar(select(Printer).where(Printer.code == "ad5x"))
        if printer is None:
            raise
    return printer


async def transition_job(
    session: AsyncSession,
    *,
    owner: User,
    job_id: UUID,
    expected_version: int,
    action: str,
    note: str | None = None,
) -> PrintJob:
    require_owner(owner)
    job = await session.get(PrintJob, job_id)
    if job is None:
        raise WorkflowNotFoundError
    rule = JOB_ACTIONS.get(action)
    if rule is None or job.status not in rule[0]:
        raise WorkflowConflictError(
            "This action is not available for the current production state."
        )
    if action in {"hold", "print_failed", "qa_fail"} and not (note or "").strip():
        raise WorkflowConflictError("This action requires an operator note.")
    order = await session.get(Order, job.order_id)
    assert order is not None
    if action in {"prepare", "manual_started"}:
        first = await session.scalar(
            select(PrintJob.id)
            .where(
                PrintJob.status.in_(
                    ["queued", "preparing", "ready_to_print", "authorized", "claimed", "printing"]
                )
            )
            .order_by(PrintJob.queue_rank, PrintJob.id)
            .limit(1)
        )
        if first != job.id:
            raise WorkflowConflictError("Only the first available job can be prepared or started.")
        if await session.scalar(
            select(PrintJob.id).where(
                PrintJob.id != job.id, PrintJob.status.in_(["printing", "claimed", "authorized"])
            )
        ):
            raise WorkflowConflictError("The printer already has an active job.")
        await manifest(session, job)
        printer = await singleton_printer(session)
        reserved = await session.scalar(
            update(Printer)
            .where(
                Printer.id == printer.id,
                (Printer.active_job_id.is_(None)) | (Printer.active_job_id == job.id),
            )
            .values(active_job_id=job.id)
            .returning(Printer.id)
        )
        if reserved is None:
            raise WorkflowConflictError("The printer slot is reserved by another job.")
        job.printer_id = printer.id
    if action == "manual_started":
        readiness = await session.scalar(
            select(PrintReadinessCheck)
            .where(PrintReadinessCheck.print_job_id == job.id)
            .order_by(PrintReadinessCheck.completed_at.desc())
        )
        _, digest = await manifest(session, job)
        if (
            readiness is None
            or utc(readiness.completed_at) < utc() - timedelta(minutes=10)
            or (readiness.manifest_sha256 != digest)
        ):
            raise WorkflowConflictError(
                "Complete a fresh readiness checklist for this exact artifact."
            )
        job.started_at = utc()
    await compare_version(session, PrintJob, job, expected_version)
    await compare_version(session, Order, order, order.version)
    job.status = rule[1]
    order.status = rule[2]
    job.owner_note = (note or "").strip() or None
    if action in {"hold", "print_completed", "print_failed", "qa_fail", "qa_pass"}:
        await session.execute(
            update(Printer).where(Printer.active_job_id == job.id).values(active_job_id=None)
        )
    if action in {"qa_pass", "qa_fail", "print_failed"}:
        job.completed_at = utc()
    session.add(
        PrintJobEvent(
            print_job_id=job.id,
            event_type=action,
            source_event_id=f"owner:{job.id}:{job.version}",
            actor_user_id=owner.id,
            observed_at=utc(),
            received_at=utc(),
            details={"note": job.owner_note} if job.owner_note else {},
        )
    )
    audit(session, AuditEventType.PRINT_JOB_CHANGED, owner, job.id, {"action": action})
    await request_notice(session, "buyer.order_updated", "order", order.id, order.buyer_id)
    if action in {"print_failed", "qa_fail"}:
        await request_notice(session, "owner.print_failed", "print_job", job.id)
    await session.commit()
    return job


async def complete_readiness(
    session: AsyncSession,
    *,
    owner: User,
    job_id: UUID,
    expected_version: int,
    checklist: dict[str, bool],
) -> PrintJob:
    require_owner(owner)
    fields = {"bedClear", "materialLoaded", "nozzleChecked", "areaClear", "artifactReviewed"}
    if set(checklist) != fields or any(value is not True for value in checklist.values()):
        raise WorkflowConflictError("Confirm every readiness check before preparing the print.")
    job = await session.get(PrintJob, job_id)
    if job is None:
        raise WorkflowNotFoundError
    if job.status not in {"preparing", "ready_to_print"}:
        raise WorkflowConflictError("Prepare this job before completing its readiness checklist.")
    _, digest = await manifest(session, job)
    await compare_version(session, PrintJob, job, expected_version)
    order = await session.get(Order, job.order_id)
    assert order is not None
    await compare_version(session, Order, order, order.version)
    session.add(
        PrintReadinessCheck(
            print_job_id=job.id,
            printer_id=job.printer_id,
            completed_by_user_id=owner.id,
            checklist_version="manual-orca/1",
            checklist_snapshot=checklist,
            manifest_sha256=digest,
            completed_at=utc(),
        )
    )
    job.status = "ready_to_print"
    order.status = "ready_to_print"
    audit(session, AuditEventType.PRINT_READINESS_COMPLETED, owner, job.id)
    await session.commit()
    return job


async def update_fulfillment(
    session: AsyncSession,
    *,
    owner: User,
    order_id: UUID,
    expected_version: int,
    status: str,
    carrier_name: str | None = None,
    tracking_reference: str | None = None,
) -> Fulfillment:
    require_owner(owner)
    order = await session.get(Order, order_id)
    if order is None:
        raise WorkflowNotFoundError
    successful = await session.scalar(
        select(PrintJob.id).where(PrintJob.order_id == order.id, PrintJob.status == "completed")
    )
    if successful is None or order.status not in {
        "qa",
        "ready_for_pickup",
        "out_for_delivery",
        "shipped",
    }:
        raise WorkflowConflictError("Fulfilment requires a successful print and quality check.")
    fulfillment = await session.scalar(select(Fulfillment).where(Fulfillment.order_id == order_id))
    if fulfillment is None:
        raise WorkflowConflictError("The accepted fulfilment selection is missing.")
    initial = {
        "pickup": "ready_for_pickup",
        "local_delivery": "out_for_delivery",
        "shipping": "shipped",
    }
    expected = initial[fulfillment.mode]
    if fulfillment.status == "pending":
        if status != expected:
            raise WorkflowConflictError(f"This order must first be marked {expected}.")
        if fulfillment.mode == "shipping" and not (
            (carrier_name or "").strip() and (tracking_reference or "").strip()
        ):
            raise WorkflowConflictError("Shipping requires a carrier and tracking reference.")
    elif fulfillment.status == expected:
        if status != "completed":
            raise WorkflowConflictError("Record collection or delivery to complete this order.")
    else:
        raise WorkflowConflictError("This fulfilment transition is not available.")
    await compare_version(session, Order, order, expected_version)
    fulfillment.status = status
    fulfillment.prepared_by_user_id = owner.id
    if status == expected:
        fulfillment.carrier_name = (carrier_name or "").strip() or None
        fulfillment.tracking_reference = (tracking_reference or "").strip() or None
        fulfillment.dispatched_at = utc()
    else:
        fulfillment.completed_at = utc()
        fulfillment.delivered_at = utc()
        order.completed_at = utc()
    order.status = status
    audit(session, AuditEventType.FULFILLMENT_CHANGED, owner, order.id, {"status": status})
    await request_notice(session, "buyer.order_updated", "order", order.id, order.buyer_id)
    await session.commit()
    return fulfillment
