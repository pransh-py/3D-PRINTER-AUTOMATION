"""Transactional, private and recoverable workflow email in disposable state."""

from asyncio import run
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from test_commerce import seed_commerce

from xxx_api.config import Settings
from xxx_api.email import EmailDeliveryError
from xxx_api.models.analysis import OutboxEvent
from xxx_api.models.notifications import Notification
from xxx_api.services.commerce import WorkflowNotFoundError, accept_quote, issue_quote
from xxx_api.services.notifications import (
    deliver_notifications,
    publish_notifications,
    request_notice,
    retry_notification,
)


class MailSink:
    def __init__(self, failing=False):
        self.messages = []
        self.failing = failing

    async def send_notice(self, recipient, *, subject, body, message_id):
        if self.failing:
            raise EmailDeliveryError("PRIVATE SMTP RESPONSE must not be persisted")
        self.messages.append((recipient, subject, body, message_id))


async def seed_notices():
    engine, sessions, owner, buyer, request, estimate = await seed_commerce()
    async with sessions() as session:
        quote = await issue_quote(
            session,
            owner=owner,
            request_id=request.id,
            estimate_id=estimate.id,
            expected_version=request.version,
            expires_at=datetime.now(UTC) + timedelta(hours=3),
        )
    return engine, sessions, owner, buyer, request, estimate, quote


def test_disabled_notifications_do_not_send_or_consume():
    async def scenario():
        engine, sessions, _owner, buyer, _request, _estimate, quote = await seed_notices()
        try:
            async with sessions() as session:
                await accept_quote(session, buyer=buyer, quote_id=quote.id)
                assert await session.scalar(select(func.count()).select_from(OutboxEvent)) > 0
            sink = MailSink()
            settings = Settings(environment="test")
            assert await publish_notifications(sessions, settings) == 0
            assert await deliver_notifications(sessions, settings, sink) == 0
            assert sink.messages == []
        finally:
            await engine.dispose()

    run(scenario())


def test_atomic_fanout_idempotence_and_private_templates():
    async def scenario():
        engine, sessions, owner, buyer, _request, _estimate, quote = await seed_notices()
        try:
            settings = Settings(environment="test", workflow_notifications_enabled=True)
            async with sessions() as session:
                order = await accept_quote(session, buyer=buyer, quote_id=quote.id)
                await accept_quote(session, buyer=buyer, quote_id=quote.id)
                events = list(
                    await session.scalars(
                        select(OutboxEvent).where(OutboxEvent.topic == "notification.requested")
                    )
                )
                assert len(events) == 3  # issuance buyer + acceptance buyer and owner
                assert all(
                    set(row.payload) == {"schemaVersion", "recipientUserId", "templateCode"}
                    for row in events
                )
                assert "@" not in str([row.payload for row in events])
            assert await publish_notifications(sessions, settings) == 3
            assert await publish_notifications(sessions, settings) == 0
            sink = MailSink()
            assert await deliver_notifications(sessions, settings, sink) == 3
            assert await deliver_notifications(sessions, settings, sink) == 0
            assert {message[0] for message in sink.messages} == {owner.email, buyer.email}
            for _recipient, _subject, body, message_id in sink.messages:
                assert "http://localhost:3000/" in body
                assert order.public_reference not in body
                assert "storageKey" not in body and "11800" not in body
                assert message_id.startswith("<workflow-")
            async with sessions() as session:
                notices = list(await session.scalars(select(Notification)))
                assert all(row.status == "sent" and row.sent_at for row in notices)
                assert all(row.lease_token is None for row in notices)
        finally:
            await engine.dispose()

    run(scenario())


def test_failure_backoff_dead_letter_and_owner_retry():
    async def scenario():
        engine, sessions, owner, buyer, _request, _estimate, _quote = await seed_notices()
        try:
            settings = Settings(
                environment="test", workflow_notifications_enabled=True, notification_max_attempts=2
            )
            await publish_notifications(sessions, settings)
            now = datetime.now(UTC)
            sink = MailSink(failing=True)
            assert await deliver_notifications(sessions, settings, sink, now=now) == 1
            assert await deliver_notifications(sessions, settings, sink, now=now) == 0
            async with sessions() as session:
                row = await session.scalar(select(Notification))
                assert row.status == "failed" and row.attempt_count == 1
                assert row.last_error_code == "smtp_unavailable"
            assert (
                await deliver_notifications(
                    sessions, settings, sink, now=now + timedelta(minutes=2)
                )
                == 1
            )
            async with sessions() as session:
                row = await session.scalar(select(Notification))
                assert row.status == "dead_lettered" and row.attempt_count == 2
                notification_id = row.id
                with pytest.raises(WorkflowNotFoundError):
                    await retry_notification(session, buyer, row.id)
                await session.rollback()
                await retry_notification(session, owner, notification_id)
            sink.failing = False
            assert (
                await deliver_notifications(
                    sessions, settings, sink, now=now + timedelta(minutes=3)
                )
                == 1
            )
            assert len(sink.messages) == 1
        finally:
            await engine.dispose()

    run(scenario())


def test_destination_change_and_role_confusion_fail_closed():
    async def scenario():
        engine, sessions, owner, buyer, _request, _estimate, _quote = await seed_notices()
        try:
            settings = Settings(environment="test", workflow_notifications_enabled=True)
            await publish_notifications(sessions, settings)
            async with sessions() as session:
                live = await session.get(type(buyer), buyer.id)
                live.email = "changed@lab.example"
                await session.commit()
            sink = MailSink()
            assert await deliver_notifications(sessions, settings, sink) == 1
            assert sink.messages == []
            async with sessions() as session:
                row = await session.scalar(select(Notification))
                assert row.status == "dead_lettered"
                assert row.last_error_code == "recipient_changed"
                await request_notice(session, "buyer.quote_issued", "quote", uuid4(), owner.id)
                await session.commit()
            await publish_notifications(sessions, settings)
            assert await deliver_notifications(sessions, settings, sink) == 0
            assert sink.messages == []
        finally:
            await engine.dispose()

    run(scenario())


def test_uncommitted_business_event_has_no_notice_and_expired_lease_recovers():
    async def scenario():
        engine, sessions, _owner, buyer, _request, _estimate, _quote = await seed_notices()
        try:
            settings = Settings(environment="test", workflow_notifications_enabled=True)
            async with sessions() as session:
                await request_notice(session, "buyer.order_updated", "order", uuid4(), buyer.id)
                await session.rollback()
            assert await publish_notifications(sessions, settings) == 1  # quote issue only
            now = datetime.now(UTC)
            async with sessions() as session:
                row = await session.scalar(select(Notification))
                await session.execute(
                    update(Notification)
                    .where(Notification.id == row.id)
                    .values(lease_token=uuid4(), lease_expires_at=now + timedelta(minutes=2))
                )
                await session.commit()
            sink = MailSink()
            assert await deliver_notifications(sessions, settings, sink, now=now) == 0
            assert (
                await deliver_notifications(
                    sessions, settings, sink, now=now + timedelta(minutes=3)
                )
                == 1
            )
            assert len(sink.messages) == 1
        finally:
            await engine.dispose()

    run(scenario())


def test_last_attempt_crash_is_visible_not_stranded_or_auto_resent():
    async def scenario():
        engine, sessions, _owner, _buyer, _request, _estimate, _quote = await seed_notices()
        try:
            settings = Settings(
                environment="test", workflow_notifications_enabled=True, notification_max_attempts=1
            )
            await publish_notifications(sessions, settings)
            now = datetime.now(UTC)
            async with sessions() as session:
                row = await session.scalar(select(Notification))
                await session.execute(
                    update(Notification)
                    .where(Notification.id == row.id)
                    .values(
                        attempt_count=1,
                        lease_token=uuid4(),
                        lease_expires_at=now - timedelta(seconds=1),
                    )
                )
                await session.commit()
            sink = MailSink()
            assert await deliver_notifications(sessions, settings, sink, now=now) == 0
            assert sink.messages == []
            async with sessions() as session:
                row = await session.scalar(select(Notification))
                assert row.status == "dead_lettered"
                assert row.last_error_code == "delivery_uncertain"
                assert row.lease_token is None
        finally:
            await engine.dispose()

    run(scenario())
