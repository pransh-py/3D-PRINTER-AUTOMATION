"""Phone-only buyer identity; capturing delivery is test-only, never a runtime fallback."""

from asyncio import run
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_auth_http import ORIGIN, _build_app

from xxx_api.config import Settings
from xxx_api.models.identity import PhoneOtpChallenge, User
from xxx_api.phone_otp import PhoneOtpDeliveryError

PHONE = "+919000000001"


@dataclass
class CapturingOtpSender:
    sent: list[tuple[str, str]] = field(default_factory=list)
    failure: str | None = None

    async def send_code(self, phone_e164: str, code: str) -> None:
        if self.failure:
            raise PhoneOtpDeliveryError(self.failure)
        self.sent.append((phone_e164, code))


def build():
    app, engine, _, limiter = _build_app()
    app.state.settings = Settings(
        environment="test",
        allowed_origins=[ORIGIN],
        whatsapp_otp_enabled=True,
        whatsapp_otp_sender_api_key=SecretStr("test-only-" + "k" * 48),
    )
    sender = CapturingOtpSender()
    app.state.phone_otp_sender = sender
    return app, engine, sender, limiter


def request(client, purpose="signup", **changes):
    body = {"phone": PHONE, "purpose": purpose}
    if purpose == "signup":
        body["displayName"] = "Phone buyer"
    body.update(changes)
    return client.post("/api/v1/auth/phone/request", headers={"Origin": ORIGIN}, json=body)


def verify(client, challenge, code):
    return client.post(
        "/api/v1/auth/phone/verify",
        headers={"Origin": ORIGIN},
        json={"challenge": challenge, "code": code},
    )


def test_phone_signup_session_is_not_a_fabricated_email_or_owner():
    app, engine, sender, limiter = build()
    with TestClient(app, base_url=ORIGIN) as client:
        requested = request(client)
        assert requested.status_code == 202
        code = sender.sent[-1][1]
        assert code not in requested.text
        challenge = requested.json()["challenge"]
        response = verify(client, challenge, code)
        assert response.status_code == 200
        assert response.json()["email"] is None
        assert response.json()["phone"] == PHONE
        assert response.json()["role"] == "buyer"
        assert client.get("/api/v1/auth/me").json() == response.json()
        assert client.get("/api/v1/owner/production").status_code == 403
        assert verify(client, challenge, code).status_code == 400
        assert "phone-otp-request" in limiter.scopes and "phone-otp-verify" in limiter.scopes

    async def inspect():
        async with async_sessionmaker(engine)() as session:
            user = await session.scalar(select(User).where(User.phone_e164 == PHONE))
            assert user and user.email is None and user.password_hash is None
            assert user.email_verified_at is None and user.phone_verified_at is not None

    run(inspect())
    run(engine.dispose())


def test_wrong_guesses_expiry_and_cooldown_do_not_issue_sessions():
    app, engine, sender, _ = build()
    with TestClient(app, base_url=ORIGIN) as client:
        first = request(client).json()
        code = sender.sent[-1][1]
        second = request(client)
        assert second.status_code == 429 and int(second.headers["retry-after"]) > 0
        assert len(sender.sent) == 1
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            assert verify(client, first["challenge"], wrong).status_code == 400
        assert verify(client, first["challenge"], code).status_code == 400
        assert client.get("/api/v1/auth/me").status_code == 401
    run(engine.dispose())


def test_delivery_failure_never_claims_sent_and_can_be_retried():
    app, engine, sender, _ = build()
    with TestClient(app, base_url=ORIGIN) as client:
        sender.failure = "unavailable"
        assert request(client).status_code == 503
        assert not sender.sent
        sender.failure = None
        requested = request(client)
        assert requested.status_code == 202
    run(engine.dispose())


def test_unknown_phone_login_requires_registration_only_after_valid_proof():
    app, engine, sender, _ = build()
    with TestClient(app, base_url=ORIGIN) as client:
        requested = request(client, "login")
        assert requested.status_code == 202
        challenge = requested.json()["challenge"]
        assert verify(client, challenge, sender.sent[-1][1]).status_code == 404
        assert verify(client, challenge, sender.sent[-1][1]).status_code == 400
    run(engine.dispose())


def test_inputs_origin_and_disabled_feature_cannot_bypass_boundary():
    app, engine, sender, _ = build()
    with TestClient(app, base_url=ORIGIN) as client:
        assert (
            client.post(
                "/api/v1/auth/phone/request", json={"phone": PHONE, "purpose": "login"}
            ).status_code
            == 403
        )
        for change in [
            {"role": "owner"},
            {"purpose": "owner"},
            {"phone": "+15551234567"},
            {"phone": "9000000001"},
        ]:
            assert request(client, **change).status_code == 422
        assert request(client, "login", displayName="injected").status_code == 422
        app.state.settings.whatsapp_otp_enabled = False
        assert request(client).status_code == 503
        assert not sender.sent
    run(engine.dispose())


def test_expired_and_superseded_challenges_are_invalid():
    app, engine, sender, _ = build()

    async def age():
        async with async_sessionmaker(engine)() as session:
            await session.execute(
                update(PhoneOtpChallenge).values(
                    created_at=datetime.now(UTC) - timedelta(seconds=301),
                    expires_at=datetime.now(UTC) - timedelta(seconds=1),
                    delivered_at=datetime.now(UTC) - timedelta(seconds=61),
                )
            )
            await session.commit()

    with TestClient(app, base_url=ORIGIN) as client:
        first = request(client).json()["challenge"]
        first_code = sender.sent[-1][1]
        run(age())
        assert verify(client, first, first_code).status_code == 400
        new = request(client).json()["challenge"]
        assert verify(client, first, first_code).status_code == 400
        assert verify(client, new, sender.sent[-1][1]).status_code == 200
    run(engine.dispose())


def test_existing_phone_login_and_signup_keep_the_same_account():
    app, engine, sender, _ = build()

    async def age():
        async with async_sessionmaker(engine)() as session:
            await session.execute(
                update(PhoneOtpChallenge).values(
                    created_at=datetime.now(UTC) - timedelta(seconds=61),
                    delivered_at=datetime.now(UTC) - timedelta(seconds=61),
                )
            )
            await session.commit()

    with TestClient(app, base_url=ORIGIN) as client:
        first = request(client).json()["challenge"]
        initial = verify(client, first, sender.sent[-1][1]).json()
        for purpose in ["login", "signup"]:
            run(age())
            client.cookies.clear()
            challenge = request(client, purpose).json()["challenge"]
            response = verify(client, challenge, sender.sent[-1][1])
            assert response.status_code == 200
            assert response.json()["id"] == initial["id"]
            assert response.json()["displayName"] == initial["displayName"]
    run(engine.dispose())


def test_phone_only_buyer_can_accept_pay_and_queue_but_is_not_emailed():
    import pytest
    from test_commerce import seed_commerce
    from test_notifications import MailSink
    from test_payments import FictionalGateway, payment_settings

    from xxx_api.models.notifications import Notification
    from xxx_api.services.commerce import (
        WorkflowNotFoundError,
        accept_quote,
        enqueue_paid_orders,
        issue_quote,
    )
    from xxx_api.services.notifications import deliver_notifications, publish_notifications
    from xxx_api.services.payments import create_checkout, reconcile_intent

    async def scenario():
        engine, sessions, owner, buyer, quote_request, estimate = await seed_commerce()
        try:
            async with sessions() as session:
                buyer = await session.get(User, buyer.id)
                buyer.email = buyer.password_hash = buyer.email_verified_at = None
                buyer.phone_e164, buyer.phone_verified_at = PHONE, datetime.now(UTC)
                await session.commit()
                quote = await issue_quote(
                    session,
                    owner=owner,
                    request_id=quote_request.id,
                    estimate_id=estimate.id,
                    expected_version=quote_request.version,
                    expires_at=datetime.now(UTC) + timedelta(hours=2),
                )
                order = await accept_quote(session, buyer=buyer, quote_id=quote.id)
                gateway, settings = FictionalGateway(), payment_settings()
                intent = await create_checkout(
                    session, buyer=buyer, order_id=order.id, settings=settings, gateway=gateway
                )
                gateway.capture()
                await reconcile_intent(session, settings=settings, gateway=gateway, intent=intent)
                assert await enqueue_paid_orders(session) == 1
                buyer.email, buyer.password_hash = "buyer@lab.example", "unused"
                buyer.phone_e164 = buyer.phone_verified_at = None
                await session.commit()
                with pytest.raises(WorkflowNotFoundError):
                    await accept_quote(session, buyer=buyer, quote_id=quote.id)
                buyer.email = buyer.password_hash = None
                buyer.phone_e164, buyer.phone_verified_at = PHONE, datetime.now(UTC)
                await session.commit()
            notices = Settings(environment="test", workflow_notifications_enabled=True)
            await publish_notifications(sessions, notices)
            sink = MailSink()
            await deliver_notifications(sessions, notices, sink)
            assert all(recipient != PHONE for recipient, *_ in sink.messages)
            async with sessions() as session:
                rows = list(
                    await session.scalars(
                        select(Notification).where(Notification.recipient_user_id == buyer.id)
                    )
                )
                assert rows and all(
                    row.status == "dead_lettered" and row.last_error_code == "recipient_unavailable"
                    for row in rows
                )
        finally:
            await engine.dispose()

    run(scenario())


def test_phone_concurrency_reserves_one_send_five_guesses_and_one_session(tmp_path):
    from asyncio import Event, gather

    from sqlalchemy import func
    from sqlalchemy.ext.asyncio import create_async_engine

    from xxx_api.models import Base
    from xxx_api.models.identity import RefreshSession
    from xxx_api.services.phone_auth import (
        InvalidPhoneCodeError,
        PhoneOtpCooldownError,
        issue_phone_challenge,
        verify_phone_challenge,
    )

    async def scenario():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'phone-races.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        settings = Settings(environment="test")
        sender = CapturingOtpSender()
        entered, release = Event(), Event()

        class PausingSender:
            async def send_code(self, phone_e164, code):
                await sender.send_code(phone_e164, code)
                entered.set()
                await release.wait()

        async def issue(delivery, number=PHONE):
            async with sessions() as session:
                try:
                    return await issue_phone_challenge(
                        session,
                        settings,
                        delivery,
                        phone=number,
                        purpose="signup",
                        display_name="Race buyer",
                    )
                except PhoneOtpCooldownError:
                    return None

        import asyncio

        first = asyncio.create_task(issue(PausingSender()))
        await entered.wait()
        assert await issue(sender) is None
        release.set()
        challenge = await first
        assert challenge and len(sender.sent) == 1
        correct = sender.sent[-1][1]

        async def check(raw, code):
            async with sessions() as session:
                try:
                    return await verify_phone_challenge(
                        session, settings, raw_challenge=raw, code=code
                    )
                except InvalidPhoneCodeError:
                    return None

        results = await gather(
            check(challenge.challenge, correct), check(challenge.challenge, correct)
        )
        assert sum(result is not None for result in results) == 1
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(RefreshSession)) == 1
        results = await gather(issue(sender, "+919000000002"), issue(sender, "+919000000002"))
        assert sum(result is not None for result in results) == 1
        assert len(sender.sent) == 2
        raw = next(result.challenge for result in results if result)
        wrong = "000000" if sender.sent[-1][1] != "000000" else "111111"
        assert not any(await gather(*(check(raw, wrong) for _ in range(10))))
        async with sessions() as session:
            row = await session.scalar(
                select(PhoneOtpChallenge).where(PhoneOtpChallenge.phone_e164 == "+919000000002")
            )
            assert row.attempt_count == 5
        await engine.dispose()

    run(scenario())


def test_populated_identity_migration_preserves_constraints_and_rows(tmp_path, monkeypatch):
    from pathlib import Path

    import pytest
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import IntegrityError

    url = f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("XXX_DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(config, "0012_model_review_audit")
    engine = create_engine(url.replace("+aiosqlite", ""))
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users(id,email,display_name,password_hash,role,status,owner_slot) "
                "VALUES(:id,'owner@lab.example','Existing owner','existing-hash',"
                "'owner','active','primary')"
            ),
            {"id": "a" * 32},
        )
    command.upgrade(config, "head")
    inspector = inspect(engine)
    names = {value["name"] for value in inspector.get_check_constraints("users")}
    assert {
        "ck_users_owner_slot",
        "ck_users_role",
        "ck_users_status",
        "ck_users_phone_verified",
        "ck_users_owner_email_only",
    } <= names
    assert any(
        value["name"] == "uq_phone_otp_active_phone" and value["unique"]
        for value in inspector.get_indexes("phone_otp_challenges")
    )
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT password_hash FROM users")).scalar_one()
            == "existing-hash"
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text("UPDATE users SET phone_e164='+919000000001',phone_verified_at=CURRENT_TIMESTAMP")
        )
    engine.dispose()


def test_sender_adapter_uses_only_authenticated_bounded_loopback_transport():
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from urllib.parse import urlparse

    import pytest

    from xxx_api.phone_otp import OtpigeonWhatsAppSender

    class Handler(BaseHTTPRequestHandler):
        mode = "ok"
        calls: ClassVar[list] = []

        def log_message(self, *_args):
            pass

        def do_POST(self):
            Handler.calls.append(
                (
                    self.path,
                    self.headers.get("X-SENDER-API-KEY"),
                    json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                )
            )
            modes = {
                "ok": (200, {"sent": True}),
                "false": (200, {"sent": False}),
                "unavailable": (503, {}),
                "unreachable": (404, {"error": "number_not_registered"}),
                "redirect": (302, {}),
                "nonjson": (200, None),
                "timeout": (200, {"sent": True}),
            }
            if Handler.mode == "timeout":
                import time

                time.sleep(0.1)
            status, body = modes[Handler.mode]
            self.send_response(status)
            self.send_header("Location", "/must-not-follow")
            self.end_headers()
            with suppress(BrokenPipeError):
                self.wfile.write(json.dumps(body).encode() if body is not None else b"not-json")

        def do_GET(self):
            Handler.calls.append((self.path, self.headers.get("X-SENDER-API-KEY"), {}))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"sent":true}')

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = Settings(
            environment="test",
            whatsapp_otp_enabled=True,
            whatsapp_otp_sender_api_key="test-only-" + "k" * 48,
            whatsapp_otp_sender_url=f"http://127.0.0.1:{server.server_port}",
        )
        adapter = OtpigeonWhatsAppSender(settings)
        run(adapter.send_code(PHONE, "004219"))
        assert Handler.calls[-1][1] == settings.whatsapp_otp_sender_api_key.get_secret_value()
        assert Handler.calls[-1][2] == {"phone": PHONE, "otp": "004219"}
        for mode, reason in [
            ("false", "failed"),
            ("nonjson", "failed"),
            ("redirect", "failed"),
            ("unavailable", "unavailable"),
            ("unreachable", "unreachable_number"),
        ]:
            Handler.mode = mode
            with pytest.raises(PhoneOtpDeliveryError) as error:
                run(adapter.send_code(PHONE, "004219"))
            assert error.value.reason == reason
        assert all(path == "/send-otp" for path, *_ in Handler.calls)
        Handler.mode = "timeout"
        settings.whatsapp_otp_timeout_seconds = 0.02
        with pytest.raises(PhoneOtpDeliveryError) as error:
            run(adapter.send_code(PHONE, "004219"))
        assert error.value.reason == "unavailable"
        assert urlparse(str(settings.whatsapp_otp_sender_url)).hostname == "127.0.0.1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_phone_settings_fail_closed_for_public_weak_or_production_configuration():
    import pytest
    from pydantic import ValidationError

    valid = {
        "environment": "test",
        "whatsapp_otp_enabled": True,
        "whatsapp_otp_sender_api_key": "test-only-" + "k" * 48,
    }
    for change in [
        {"whatsapp_otp_sender_url": "https://example.com"},
        {"whatsapp_otp_sender_url": "http://127.0.0.1:3201/path"},
        {"whatsapp_otp_sender_api_key": "short"},
        {"whatsapp_otp_sender_api_key": Settings().token_hash_secret},
        {"environment": "production"},
    ]:
        with pytest.raises(ValidationError):
            Settings(**(valid | change))


def test_private_local_models_accept_ipv6_loopback_but_not_other_ipv6_or_public_hosts(tmp_path):
    import pytest
    from pydantic import ValidationError

    base = {
        "environment": "test",
        "storage_backend": "local",
        "storage_local_directory": tmp_path / "models",
    }
    origin = "http://[::1]:3115"
    Settings(**base, public_web_url=origin, allowed_origins=[origin])
    for origin in ["http://example.com", "http://[2001:db8::1]:3115"]:
        with pytest.raises(ValidationError):
            Settings(**base, public_web_url=origin, allowed_origins=[origin])
