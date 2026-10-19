"""Adversarial payment/production workflow in the dedicated disposable PostgreSQL lab.

Requires the specifically named loopback Docker lab from LOCAL_WORKFLOW.md. It never
accepts a production URL. All identity, rates, analysis and gateway responses are fictional.
"""

import asyncio
import json
import sys
from os import environ
from pathlib import Path
from subprocess import run
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api/tests"))

from test_commerce import seed_commerce  # noqa: E402
from test_payments import FictionalGateway, accepted, payment_settings, signed_payload  # noqa: E402
from xxx_api.models.analysis import OutboxEvent  # noqa: E402
from xxx_api.models.commerce import Order, PaymentAttempt, PaymentIntent, PrintJob  # noqa: E402
from xxx_api.models.notifications import Notification  # noqa: E402
from xxx_api.email import SmtpEmailSender  # noqa: E402
from xxx_api.services.commerce import (  # noqa: E402
    WorkflowConflictError,
    complete_readiness,
    enqueue_paid_orders,
    transition_job,
    update_fulfillment,
)
from xxx_api.services.payments import create_checkout, ingest_webhook  # noqa: E402
from xxx_api.services.notifications import deliver_notifications, publish_notifications  # noqa: E402

LAB_URL = "postgresql+psycopg://payment_lab:fictional-disposable-lab@127.0.0.1:55439/payment_lab"


async def verify(url: str) -> None:
    engine, sessions, owner, buyer, request, estimate = await seed_commerce(url)
    settings = payment_settings().model_copy(
        update={"workflow_notifications_enabled": True, "smtp_port": 51025}
    )
    gateway = FictionalGateway()
    try:
        async with sessions() as session:
            order = await accepted(session, owner, buyer, request, estimate)
            order_id = order.id

        async def checkout():
            async with sessions() as session:
                try:
                    return await create_checkout(
                        session,
                        buyer=buyer,
                        order_id=order_id,
                        settings=settings,
                        gateway=gateway,
                    )
                except WorkflowConflictError:
                    return None

        await asyncio.gather(*(checkout() for _ in range(5)))
        assert gateway.creates == 1
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(PaymentIntent))
                == 1
            )
            assert await enqueue_paid_orders(session) == 0
        gateway.capture()
        raw, signature = signed_payload(gateway, settings)

        async def deliver(index):
            async with sessions() as session:
                return await ingest_webhook(
                    session,
                    raw=raw,
                    signature=signature,
                    provider_event_id=f"evt_Postgres{index % 2}",
                    settings=settings,
                    gateway=gateway,
                )

        await asyncio.gather(*(deliver(index) for index in range(6)))
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(PaymentAttempt))
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .where(OutboxEvent.topic == "production.requested")
                )
                == 1
            )
            assert await enqueue_paid_orders(session) == 1
            assert await enqueue_paid_orders(session) == 0
            job = await session.scalar(
                select(PrintJob).where(PrintJob.order_id == order_id)
            )
            job = await transition_job(
                session,
                owner=owner,
                job_id=job.id,
                expected_version=job.version,
                action="prepare",
            )
            job = await complete_readiness(
                session,
                owner=owner,
                job_id=job.id,
                expected_version=job.version,
                checklist={
                    "bedClear": True,
                    "materialLoaded": True,
                    "nozzleChecked": True,
                    "areaClear": True,
                    "artifactReviewed": True,
                },
            )
            for action in ("manual_started", "print_completed", "qa_pass"):
                job = await transition_job(
                    session,
                    owner=owner,
                    job_id=job.id,
                    expected_version=job.version,
                    action=action,
                )
            order = await session.get(Order, order_id)
            await session.refresh(order)
            await update_fulfillment(
                session,
                owner=owner,
                order_id=order.id,
                expected_version=order.version,
                status="ready_for_pickup",
            )
            await session.refresh(order)
            await update_fulfillment(
                session,
                owner=owner,
                order_id=order.id,
                expected_version=order.version,
                status="completed",
            )
            await session.refresh(order)
            assert order.status == "completed"
            report = {
                "labOnly": True,
                "database": "isolated PostgreSQL 17",
                "databaseName": url.rsplit("/", 1)[1],
                "realRazorpayCalled": False,
                "physicalPrinterCommands": 0,
                "concurrentCheckoutRequests": 5,
                "providerCreateCalls": gateway.creates,
                "concurrentWebhookDeliveries": 6,
                "capturedAttempts": 1,
                "productionOutboxEffects": 1,
                "printJobs": 1,
                "qa": "passed (operator-record fixture)",
                "orderStatus": order.status,
            }
        # Real SMTP delivery to an isolated loopback Mailpit sink, never an external mailbox.
        published = await asyncio.gather(
            *(publish_notifications(sessions, settings) for _ in range(4))
        )
        delivered = await asyncio.gather(
            *(
                deliver_notifications(
                    sessions, settings, SmtpEmailSender(settings), limit=20
                )
                for _ in range(4)
            )
        )
        async with sessions() as session:
            notices = list(await session.scalars(select(Notification)))
            assert len(notices) == 12
            assert all(
                notice.status == "sent" and notice.attempt_count == 1
                for notice in notices
            )
            assert sum(published) == 12 and sum(delivered) == 12
            report.update(
                {
                    "smtpDestination": "loopback Mailpit only",
                    "notificationRecords": len(notices),
                    "smtpAccepted": sum(delivered),
                    "concurrentNotificationWorkers": 4,
                }
            )
            destination = ROOT / ".local/workflow/payment-postgres.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(report, indent=2))
            print(json.dumps(report, indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    info = json.loads(
        run(
            ["docker", "inspect", "printflow-payments-lab-20261011"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )[0]
    assert info["Config"]["Image"] == "postgres:17.10-alpine3.23"
    assert "POSTGRES_DB=payment_lab" in info["Config"]["Env"]
    mail = json.loads(
        run(
            ["docker", "inspect", "printflow-mail-lab-20261011"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )[0]
    assert mail["Config"]["Image"] == "axllent/mailpit:v1.30.0"
    # New database per run: no reset or cleanup of previous diagnostic state.
    name = f"lab_payment_{uuid4().hex}"
    admin = create_engine(LAB_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    url = LAB_URL.rsplit("/", 1)[0] + "/" + name
    previous = environ.get("XXX_DATABASE_URL")
    try:
        environ["XXX_DATABASE_URL"] = url
        config = Config(str(ROOT / "services/api/alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "services/api/migrations"))
        command.upgrade(config, "head")
        asyncio.run(verify(url))
    finally:
        if previous is None:
            environ.pop("XXX_DATABASE_URL", None)
        else:
            environ["XXX_DATABASE_URL"] = previous
