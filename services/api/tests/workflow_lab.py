"""Loopback-only browser fixture. Never import this module into production.

Run uvicorn workflow_lab:create_lab --factory --app-dir services/api/tests on loopback port 8011.
Fixtures are fictional; no Razorpay API, Redis or physical printer is contacted. The
explicit product lab submits notices only to the dedicated loopback SMTP sink.
"""

from contextlib import asynccontextmanager
from datetime import timedelta
from hashlib import sha256
from json import dumps
from pathlib import Path
from secrets import token_urlsafe
from tempfile import mkdtemp
from uuid import uuid4

import pyotp
from pydantic import SecretStr
from sqlalchemy import select
from test_commerce import seed_commerce, seed_payment

from xxx_api.config import Settings
from xxx_api.domain.auth import MfaMethodKind
from xxx_api.email import SmtpEmailSender
from xxx_api.main import create_app
from xxx_api.models.analysis import AnalysisAssetResult
from xxx_api.models.identity import MfaMethod
from xxx_api.security.mfa import encrypt_totp_secret
from xxx_api.security.passwords import hash_password
from xxx_api.services.commerce import (
    accept_quote,
    enqueue_paid_orders,
    issue_quote,
    record_captured_payment,
    utc,
)
from xxx_api.services.notifications import deliver_notifications, publish_notifications


class LabLimiter:
    async def enforce(self, scope, rules):
        assert scope and rules


class LabStorage:
    """Only a harmless comment-only artifact exists; no real model or printer command."""

    data = b"; LAB ONLY - NOT PRINTABLE\n; no motion, heater or printer commands\n"

    async def download_to_path(self, key, destination, *, max_bytes):
        if key != "lab/approved.gcode" or len(self.data) > max_bytes:
            raise ValueError("This isolated browser fixture has no such object")
        destination.write_bytes(self.data)
        return len(self.data)

    def close(self):
        pass


def create_lab(*, payments=False, notifications=False):
    root = Path(__file__).resolve().parents[3]
    lab_root = root / ".local/workflow"
    lab_root.mkdir(parents=True, exist_ok=True)
    directory = Path(mkdtemp(prefix="browser-", dir=lab_root))
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite+aiosqlite:///{directory / 'lab.db'}",
        allowed_origins=["http://127.0.0.1:3100"],
        public_web_url="http://127.0.0.1:3100",
        jwt_signing_secret=SecretStr(token_urlsafe(48)),
        token_hash_secret=SecretStr(token_urlsafe(48)),
        mfa_encryption_secret=SecretStr(token_urlsafe(48)),
        razorpay_enabled=payments,
        razorpay_checkout_name="FICTIONAL TEST STORE" if payments else None,
        razorpay_key_id="rzp_test_Fictional" if payments else None,
        razorpay_key_secret=SecretStr(token_urlsafe(32)) if payments else None,
        razorpay_webhook_secret=SecretStr(token_urlsafe(32)) if payments else None,
        workflow_notifications_enabled=notifications,
        smtp_port=51025,
    )
    app = create_app(settings)

    @asynccontextmanager
    async def lifespan(_app):
        engine, sessions, owner, buyer, request, estimate = await seed_commerce(
            settings.database_url
        )
        password = token_urlsafe(24)
        secret = pyotp.random_base32()
        async with sessions() as session:
            for user in (owner, buyer):
                user.password_hash = hash_password(password)
                session.add(user)
            method_id = uuid4()
            session.add(
                MfaMethod(
                    id=method_id,
                    user_id=owner.id,
                    kind=MfaMethodKind.TOTP,
                    encrypted_secret=encrypt_totp_secret(secret, owner.id, method_id, settings),
                    enabled_at=utc(),
                )
            )
            result = await session.scalar(select(AnalysisAssetResult))
            result.artifact_sha256 = sha256(LabStorage.data).hexdigest()
            await session.commit()
            # Fictional commercial values and captured evidence. No business rates or real payment.
            quote = await issue_quote(
                session,
                owner=owner,
                request_id=request.id,
                estimate_id=estimate.id,
                expected_version=4,
                expires_at=utc() + timedelta(hours=2),
                reason="LAB ONLY fixture, not a business quotation",
            )
            order = await accept_quote(session, buyer=buyer, quote_id=quote.id)
            if not payments:
                intent, event = await seed_payment(session, order)
                await record_captured_payment(
                    session,
                    event_id=event.id,
                    intent_id=intent.id,
                    provider_order_id="order_lab",
                    provider_payment_id="pay_lab",
                    amount_paise=order.amount_paise,
                    currency="INR",
                    captured=True,
                )
                await enqueue_paid_orders(session)
        info = directory / "access.json"
        info.touch(mode=0o600, exist_ok=False)
        info.write_text(
            dumps(
                {
                    "ownerEmail": owner.email,
                    "buyerEmail": buyer.email,
                    "password": password,
                    "totpSecret": secret,
                    "orderId": str(order.id),
                },
                indent=2,
            )
        )
        print(f"LAB ONLY access file: {info}", flush=True)
        app.state.lab_access_file = info
        if payments:
            from test_payments import FictionalGateway

            class BrowserDemoGateway(FictionalGateway):
                async def fetch_order(self, order_id):
                    # Explicit fictional demo: the first status check simulates capture.
                    # Never used by create_app or any production adapter.
                    if self.order is not None and self.order.status == "created":
                        self.capture()
                    return await super().fetch_order(order_id)

            app.state.payment_gateway = BrowserDemoGateway()
        await app.state.database_engine.dispose()
        app.state.object_storage.close()
        app.state.database_engine = engine
        app.state.session_factory = sessions
        app.state.rate_limiter = LabLimiter()
        app.state.object_storage = LabStorage()
        if notifications:
            await publish_notifications(sessions, settings)
            await deliver_notifications(sessions, settings, SmtpEmailSender(settings))
        try:
            yield
        finally:
            await app.state.redis.aclose()
            await engine.dispose()

    app.router.lifespan_context = lifespan
    return app


def create_payment_lab():
    """Unpaid browser journey with an explicit in-process fictional provider."""
    return create_lab(payments=True)


def create_local_product_lab():
    """Fictional gateway plus real delivery to the dedicated loopback Mailpit sink."""
    return create_lab(payments=True, notifications=True)
