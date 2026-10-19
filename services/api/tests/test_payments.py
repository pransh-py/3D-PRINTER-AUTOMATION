"""Fictional gateway contract tests; never contact Razorpay or physical hardware."""

import hashlib
import hmac
import json
from asyncio import run
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from test_commerce import seed_commerce

from xxx_api.config import Settings
from xxx_api.models.analysis import OutboxEvent
from xxx_api.models.commerce import Order, PaymentAttempt, PaymentProviderEvent, PrintJob
from xxx_api.razorpay import GatewayUnavailableError, ProviderOrder, ProviderPayment
from xxx_api.services.commerce import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    accept_quote,
    enqueue_paid_orders,
    issue_quote,
)
from xxx_api.services.payments import (
    checkout_return,
    create_checkout,
    ingest_webhook,
    reconcile_intent,
    reconcile_pending,
)


def payment_settings():
    return Settings(
        environment="test",
        razorpay_enabled=True,
        razorpay_mode="test",
        razorpay_key_id="rzp_test_Fictional",
        razorpay_checkout_name="FICTIONAL TEST STORE",
        razorpay_key_secret="fictional-key-secret-123",
        razorpay_webhook_secret="fictional-webhook-secret-456",
    )


class FictionalGateway:
    def __init__(self):
        self.creates = 0
        self.fail_create = False
        self.unavailable = False
        self.order = None
        self.payment = None
        self.receipt_matches = None

    async def create_order(self, *, amount, receipt):
        self.creates += 1
        self.order = ProviderOrder(
            id="order_Fictional",
            entity="order",
            amount=amount,
            receipt=receipt,
            currency="INR",
            status="created",
            amount_paid=0,
            amount_due=amount,
        )
        if self.fail_create:
            raise GatewayUnavailableError("Fictional lost response")
        return self.order

    async def find_orders(self, *, receipt):
        return self.receipt_matches if self.receipt_matches is not None else [self.order]

    async def fetch_order(self, order_id):
        if self.unavailable:
            raise GatewayUnavailableError("Fictional outage")
        return self.order

    async def fetch_payment(self, payment_id):
        return self.payment

    async def order_payments(self, order_id):
        return [self.payment] if self.payment else []

    def capture(self):
        amount = self.order.amount
        self.order = self.order.model_copy(
            update={"status": "paid", "amount_paid": amount, "amount_due": 0}
        )
        self.payment = ProviderPayment(
            id="pay_Fictional",
            entity="payment",
            order_id=self.order.id,
            amount=amount,
            currency="INR",
            status="captured",
            captured=True,
            amount_refunded=0,
        )


async def accepted(session, owner, buyer, request, estimate):
    quote = await issue_quote(
        session,
        owner=owner,
        request_id=request.id,
        estimate_id=estimate.id,
        expected_version=4,
        expires_at=datetime.now(UTC) + timedelta(hours=2),
    )
    return await accept_quote(session, buyer=buyer, quote_id=quote.id)


def signed_payload(gateway, settings, *, event="payment.captured", payment=None):
    raw = json.dumps(
        {
            "event": event,
            "payload": {"payment": {"entity": (payment or gateway.payment).model_dump()}},
        }
    ).encode()
    signature = hmac.new(
        settings.razorpay_webhook_secret.get_secret_value().encode(), raw, "sha256"
    ).hexdigest()
    return raw, signature


def test_checkout_exact_price_reused_and_callback_never_enqueues():
    async def scenario():
        engine, sessions, owner, buyer, request, estimate = await seed_commerce()
        settings, gateway = payment_settings(), FictionalGateway()
        async with sessions() as session:
            order = await accepted(session, owner, buyer, request, estimate)
            intent = await create_checkout(
                session, buyer=buyer, order_id=order.id, settings=settings, gateway=gateway
            )
            same = await create_checkout(
                session, buyer=buyer, order_id=order.id, settings=settings, gateway=gateway
            )
            assert same.id == intent.id and gateway.creates == 1
            assert intent.amount_paise == order.amount_paise == gateway.order.amount
            assert len(intent.payment_reference) <= 40
            signature = hmac.new(
                settings.razorpay_key_secret.get_secret_value().encode(),
                b"order_Fictional|pay_Fictional",
                "sha256",
            ).hexdigest()
            order = await checkout_return(
                session,
                buyer=buyer,
                order_id=order.id,
                payment_id="pay_Fictional",
                provider_order_id="order_Fictional",
                signature=signature,
                settings=settings,
            )
            assert order.status == "payment_processing"
            assert await session.scalar(select(func.count()).select_from(PaymentAttempt)) == 0
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .where(OutboxEvent.topic == "production.requested")
                )
                == 0
            )
            with pytest.raises(WorkflowConflictError):
                await checkout_return(
                    session,
                    buyer=buyer,
                    order_id=order.id,
                    payment_id="pay_Fictional",
                    provider_order_id="order_Attacker",
                    signature=signature,
                    settings=settings,
                )
            assert order.status == "payment_processing"
        await engine.dispose()

    run(scenario())


@pytest.mark.parametrize("path", ["webhook", "reconcile"])
def test_capture_enqueues_once_and_late_callback_does_not_regress(path):
    async def scenario():
        engine, sessions, owner, buyer, request, estimate = await seed_commerce()
        settings, gateway = payment_settings(), FictionalGateway()
        async with sessions() as session:
            order = await accepted(session, owner, buyer, request, estimate)
            intent = await create_checkout(
                session, buyer=buyer, order_id=order.id, settings=settings, gateway=gateway
            )
            gateway.capture()
            if path == "webhook":
                raw, signature = signed_payload(gateway, settings)
                for event_id in ["evt_Fictional", "evt_Fictional", "evt_Second"]:
                    event = await ingest_webhook(
                        session,
                        raw=raw,
                        signature=signature,
                        provider_event_id=event_id,
                        settings=settings,
                        gateway=gateway,
                    )
                    assert event.status == "processed"
                    assert event.payload_sha256 == hashlib.sha256(raw).hexdigest()
            else:
                await reconcile_intent(session, intent=intent, settings=settings, gateway=gateway)
                event = await session.scalar(select(PaymentProviderEvent))
                assert event.evidence_source == "api" and event.signature_validated_at is None
                assert event.api_authenticated_at is not None
                await reconcile_intent(session, intent=intent, settings=settings, gateway=gateway)
            await session.refresh(order)
            assert order.status == "paid_confirmed"
            assert await session.scalar(select(func.count()).select_from(PaymentAttempt)) == 1
            assert await enqueue_paid_orders(session) == 1
            assert await enqueue_paid_orders(session) == 0
            assert await session.scalar(select(func.count()).select_from(PrintJob)) == 1
            signature = hmac.new(
                settings.razorpay_key_secret.get_secret_value().encode(),
                b"order_Fictional|pay_Fictional",
                "sha256",
            ).hexdigest()
            await checkout_return(
                session,
                buyer=buyer,
                order_id=order.id,
                payment_id="pay_Fictional",
                provider_order_id="order_Fictional",
                signature=signature,
                settings=settings,
            )
            assert order.status == "queued"
        await engine.dispose()

    run(scenario())


@pytest.mark.parametrize(
    "fault",
    ["amount", "currency", "authorized", "refunded", "foreign_order", "receipt", "foreign_payment"],
)
def test_mismatched_or_uncaptured_provider_state_cannot_enqueue(fault):
    async def scenario():
        engine, sessions, owner, buyer, request, estimate = await seed_commerce()
        settings, gateway = payment_settings(), FictionalGateway()
        async with sessions() as session:
            order = await accepted(session, owner, buyer, request, estimate)
            await create_checkout(
                session, buyer=buyer, order_id=order.id, settings=settings, gateway=gateway
            )
            gateway.capture()
            raw, signature = signed_payload(gateway, settings)
            updates = {
                "amount": {"amount": order.amount_paise + 1},
                "currency": {"currency": "USD"},
                "authorized": {"status": "authorized", "captured": False},
                "refunded": {"amount_refunded": 1},
                "foreign_order": {"order_id": "order_Other"},
                "foreign_payment": {"id": "pay_Other"},
            }
            if fault == "receipt":
                gateway.order = gateway.order.model_copy(update={"receipt": "wrong"})
            else:
                gateway.payment = gateway.payment.model_copy(update=updates[fault])
            event = await ingest_webhook(
                session,
                raw=raw,
                signature=signature,
                provider_event_id="evt_Fictional",
                settings=settings,
                gateway=gateway,
            )
            assert event.status == "failed"
            await session.refresh(order)
            assert order.status == "payment_review"
            assert await session.scalar(select(func.count()).select_from(PaymentAttempt)) == 0
            assert await enqueue_paid_orders(session) == 0
        await engine.dispose()

    run(scenario())


def test_signed_replay_collision_invalid_signature_and_out_of_order_events():
    async def scenario():
        engine, sessions, owner, buyer, request, estimate = await seed_commerce()
        settings, gateway = payment_settings(), FictionalGateway()
        async with sessions() as session:
            order = await accepted(session, owner, buyer, request, estimate)
            await create_checkout(
                session, buyer=buyer, order_id=order.id, settings=settings, gateway=gateway
            )
            gateway.capture()
            raw, signature = signed_payload(gateway, settings)
            with pytest.raises(WorkflowConflictError, match="signature"):
                await ingest_webhook(
                    session,
                    raw=raw + b" ",
                    signature=signature,
                    provider_event_id="evt_Fictional",
                    settings=settings,
                    gateway=gateway,
                )
            assert await session.scalar(select(func.count()).select_from(PaymentProviderEvent)) == 0
            await ingest_webhook(
                session,
                raw=raw,
                signature=signature,
                provider_event_id="evt_Fictional",
                settings=settings,
                gateway=gateway,
            )
            for name in ["payment.failed", "payment.authorized"]:
                other, signed = signed_payload(gateway, settings, event=name)
                with pytest.raises(WorkflowConflictError, match="reused"):
                    await ingest_webhook(
                        session,
                        raw=other,
                        signature=signed,
                        provider_event_id="evt_Fictional",
                        settings=settings,
                        gateway=gateway,
                    )
                event = await ingest_webhook(
                    session,
                    raw=other,
                    signature=signed,
                    provider_event_id=f"evt_{name.replace('.', '_')}",
                    settings=settings,
                    gateway=gateway,
                )
                assert event.status == "ignored"
            await session.refresh(order)
            assert order.status == "paid_confirmed"
            assert await enqueue_paid_orders(session) == 1
        await engine.dispose()

    run(scenario())


def test_unknown_order_and_provider_outage_replay():
    async def scenario():
        engine, sessions, owner, buyer, request, estimate = await seed_commerce()
        settings, gateway = payment_settings(), FictionalGateway()
        async with sessions() as session:
            order = await accepted(session, owner, buyer, request, estimate)
            await create_checkout(
                session, buyer=buyer, order_id=order.id, settings=settings, gateway=gateway
            )
            gateway.capture()
            raw, signature = signed_payload(
                gateway,
                settings,
                payment=gateway.payment.model_copy(update={"order_id": "order_Unknown"}),
            )
            event = await ingest_webhook(
                session,
                raw=raw,
                signature=signature,
                provider_event_id="evt_Unknown",
                settings=settings,
                gateway=gateway,
            )
            assert event.status == "ignored"
            gateway.unavailable = True
            raw, signature = signed_payload(gateway, settings)
            with pytest.raises(GatewayUnavailableError):
                await ingest_webhook(
                    session,
                    raw=raw,
                    signature=signature,
                    provider_event_id="evt_Retry",
                    settings=settings,
                    gateway=gateway,
                )
            event = await session.scalar(
                select(PaymentProviderEvent).where(
                    PaymentProviderEvent.provider_event_id == "evt_Retry"
                )
            )
            assert event.status == "received" and event.failure_code == "provider_unavailable"
            assert await enqueue_paid_orders(session) == 0
            gateway.unavailable = False
            event = await ingest_webhook(
                session,
                raw=raw,
                signature=signature,
                provider_event_id="evt_Retry",
                settings=settings,
                gateway=gateway,
            )
            assert event.status == "processed"
            assert await enqueue_paid_orders(session) == 1
        await engine.dispose()

    run(scenario())


@pytest.mark.parametrize("found", [0, 1, 2])
def test_uncertain_order_creation_never_retries_post_and_can_recover(found):
    async def scenario():
        engine, sessions, owner, buyer, request, estimate = await seed_commerce()
        settings, gateway = payment_settings(), FictionalGateway()
        gateway.fail_create = True
        async with sessions() as session:
            order = await accepted(session, owner, buyer, request, estimate)
            order_id = order.id
            with pytest.raises(GatewayUnavailableError):
                await create_checkout(
                    session, buyer=buyer, order_id=order_id, settings=settings, gateway=gateway
                )
            with pytest.raises(WorkflowConflictError):
                await create_checkout(
                    session, buyer=buyer, order_id=order_id, settings=settings, gateway=gateway
                )
            from xxx_api.services.payments import intent_for

            intent = await intent_for(session, order_id)
            gateway.receipt_matches = [gateway.order] * found
            if found == 1:
                await reconcile_intent(session, intent=intent, settings=settings, gateway=gateway)
                assert intent.provider_order_id == gateway.order.id
                await create_checkout(
                    session, buyer=buyer, order_id=order_id, settings=settings, gateway=gateway
                )
            else:
                with pytest.raises(WorkflowConflictError):
                    await reconcile_intent(
                        session, intent=intent, settings=settings, gateway=gateway
                    )
            assert gateway.creates == 1
            assert await enqueue_paid_orders(session) == 0
        await engine.dispose()

    run(scenario())


def test_cross_buyer_payment_access_and_disabled_config():
    async def scenario():
        engine, sessions, owner, buyer, request, estimate = await seed_commerce()
        gateway = FictionalGateway()
        async with sessions() as session:
            order = await accepted(session, owner, buyer, request, estimate)
            with pytest.raises(GatewayUnavailableError):
                await create_checkout(
                    session,
                    buyer=buyer,
                    order_id=order.id,
                    settings=Settings(environment="test"),
                    gateway=gateway,
                )
            stranger = type(buyer)(
                id=uuid4(),
                role=buyer.role,
                status=buyer.status,
                email_verified_at=buyer.email_verified_at,
            )
            with pytest.raises(WorkflowNotFoundError):
                await create_checkout(
                    session,
                    buyer=stranger,
                    order_id=order.id,
                    settings=payment_settings(),
                    gateway=gateway,
                )
            assert gateway.creates == 0
        await engine.dispose()

    run(scenario())


def test_worker_reconciles_delayed_confirmation_without_a_callback():
    async def scenario():
        engine, sessions, owner, buyer, request, estimate = await seed_commerce()
        settings, gateway = payment_settings(), FictionalGateway()
        async with sessions() as session:
            order = await accepted(session, owner, buyer, request, estimate)
            order_id = order.id
            intent = await create_checkout(
                session, buyer=buyer, order_id=order.id, settings=settings, gateway=gateway
            )
            intent.created_at = datetime.now(UTC) - timedelta(minutes=5)
            await session.commit()
        gateway.capture()
        assert await reconcile_pending(sessions, settings, gateway) == 1
        assert await reconcile_pending(sessions, settings, gateway) == 0
        async with sessions() as session:
            order = await session.get(Order, order_id)
            assert order.status == "paid_confirmed"
            assert await enqueue_paid_orders(session) == 1
        await engine.dispose()

    run(scenario())


def test_payment_config_rejects_partial_mixed_and_local_live_credentials():
    with pytest.raises(ValidationError, match="requires"):
        Settings(environment="test", razorpay_enabled=True)
    for change in [
        {"razorpay_mode": "live"},
        {"razorpay_key_id": "rzp_live_Fictional"},
        {"razorpay_webhook_secret": "fictional-key-secret-123"},
    ]:
        with pytest.raises(ValidationError):
            Settings(**(payment_settings().model_dump() | change))
