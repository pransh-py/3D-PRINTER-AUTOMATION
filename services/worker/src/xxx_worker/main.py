"""Worker process entrypoint for dispatch and analysis consumption."""

from __future__ import annotations

from argparse import ArgumentParser
from asyncio import create_task, gather, run, sleep
from os import getpid
from socket import gethostname

from redis.asyncio import Redis
from xxx_api.config import Settings, get_settings
from xxx_api.database import create_database_engine, create_session_factory
from xxx_api.email import SmtpEmailSender
from xxx_api.razorpay import HttpRazorpayGateway
from xxx_api.services.commerce import enqueue_paid_orders
from xxx_api.services.notifications import deliver_notifications, publish_notifications
from xxx_api.services.payments import reconcile_pending
from xxx_api.services.pricing import create_pending_estimates
from xxx_api.storage import create_object_storage

from xxx_worker.orchestrator import (
    AnalysisOrchestrator,
    DeliveryDisposition,
    dispatch_analysis_outbox,
)
from xxx_worker.queue import AnalysisQueue
from xxx_worker.sandbox import SandboxValidator

QUEUE_BLOCK_MS = 1000


def create_worker_redis(settings: Settings) -> Redis:
    # XREADGROUP intentionally waits for work. Its network deadline must outlast
    # that wait; API rate-limit calls can keep their shorter independent timeout.
    return Redis.from_url(
        settings.redis_url,
        decode_responses=False,
        socket_timeout=max(settings.redis_socket_timeout_seconds, QUEUE_BLOCK_MS / 1000 + 2),
        socket_connect_timeout=settings.redis_socket_timeout_seconds,
    )


def _parser() -> ArgumentParser:
    parser = ArgumentParser(prog="xxx-worker")
    parser.add_argument("--once", action="store_true", help="dispatch and consume at most once")
    return parser


async def _run_worker(*, once: bool) -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    sessions = create_session_factory(engine)
    redis = create_worker_redis(settings)
    storage = create_object_storage(settings)
    consumer = f"{gethostname()}-{getpid()}"
    queue = AnalysisQueue(
        redis,
        stream=settings.analysis_stream_name,
        group=settings.analysis_consumer_group,
        consumer=consumer,
    )
    orchestrator = AnalysisOrchestrator(
        settings=settings,
        sessions=sessions,
        storage=storage,
        validator=SandboxValidator(
            command=settings.analysis_validator_command,
            timeout_seconds=settings.analysis_validator_timeout_seconds,
            sandbox_mode=settings.analysis_sandbox_mode,
            bubblewrap_command=settings.analysis_bubblewrap_command,
        ),
    )

    async def payment_loop() -> None:
        while True:
            await reconcile_pending(sessions, settings, HttpRazorpayGateway(settings), limit=3)
            await sleep(30)

    async def notification_pass() -> None:
        await publish_notifications(sessions, settings)
        await deliver_notifications(sessions, settings, SmtpEmailSender(settings), limit=3)

    async def notification_loop() -> None:
        while True:
            await notification_pass()
            await sleep(5)

    # Provider network latency must not block upload analysis or production outbox draining.
    payments = create_task(payment_loop()) if settings.razorpay_enabled and not once else None
    notices = (
        create_task(notification_loop())
        if settings.workflow_notifications_enabled and not once
        else None
    )
    try:
        await queue.ensure_group()
        while True:
            if payments is not None and payments.done():
                payments.result()  # Unexpected failures are surfaced; never silently lose recovery.
            if notices is not None and notices.done():
                notices.result()
            if once:
                await notification_pass()
                await reconcile_pending(sessions, settings, HttpRazorpayGateway(settings), limit=1)
            async with sessions() as session:
                await enqueue_paid_orders(session)
                await create_pending_estimates(session)
            await dispatch_analysis_outbox(sessions, queue)
            message = await queue.reclaim_stale(
                minimum_idle_ms=settings.analysis_lease_seconds * 1_000
            )
            if message is None:
                message = await queue.read_new(block_ms=100 if once else QUEUE_BLOCK_MS)
            if message is not None:
                disposition = await orchestrator.process(message)
                if disposition is DeliveryDisposition.ACKNOWLEDGE:
                    await queue.acknowledge(message)
            if once:
                return
            if message is None:
                await sleep(0.25)
    finally:
        background = [task for task in (notices, payments) if task is not None]
        for task in background:
            task.cancel()
        # The loop surfaces task failures above. Re-awaiting a failed task here must
        # not prevent cleanup; a failing close must not skip the remaining resources.
        try:
            await gather(*background, return_exceptions=True)
        finally:
            try:
                storage.close()
            finally:
                try:
                    await redis.aclose()
                finally:
                    await engine.dispose()


def main() -> None:
    """Run the private worker until interrupted, or one bounded iteration."""
    args = _parser().parse_args()
    run(_run_worker(once=args.once))


if __name__ == "__main__":
    main()
