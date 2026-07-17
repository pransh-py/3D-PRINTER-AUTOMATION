"""Worker process entrypoint for dispatch and analysis consumption."""

from __future__ import annotations

from argparse import ArgumentParser
from asyncio import run, sleep
from os import getpid
from socket import gethostname

from redis.asyncio import Redis
from xxx_api.config import get_settings
from xxx_api.database import create_database_engine, create_session_factory
from xxx_api.storage import S3ObjectStorage

from xxx_worker.orchestrator import (
    AnalysisOrchestrator,
    DeliveryDisposition,
    dispatch_analysis_outbox,
)
from xxx_worker.queue import AnalysisQueue
from xxx_worker.sandbox import SandboxValidator


def _parser() -> ArgumentParser:
    parser = ArgumentParser(prog="xxx-worker")
    parser.add_argument("--once", action="store_true", help="dispatch and consume at most once")
    return parser


async def _run_worker(*, once: bool) -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    sessions = create_session_factory(engine)
    redis = Redis.from_url(
        settings.redis_url,
        decode_responses=False,
        socket_timeout=settings.redis_socket_timeout_seconds,
        socket_connect_timeout=settings.redis_socket_timeout_seconds,
    )
    storage = S3ObjectStorage(settings)
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
    try:
        await queue.ensure_group()
        while True:
            await dispatch_analysis_outbox(sessions, queue)
            message = await queue.reclaim_stale(
                minimum_idle_ms=settings.analysis_lease_seconds * 1_000
            )
            if message is None:
                message = await queue.read_new(block_ms=100 if once else 1_000)
            if message is not None:
                disposition = await orchestrator.process(message)
                if disposition is DeliveryDisposition.ACKNOWLEDGE:
                    await queue.acknowledge(message)
            if once:
                return
            if message is None:
                await sleep(0.25)
    finally:
        storage.close()
        await redis.aclose()
        await engine.dispose()


def main() -> None:
    """Run the private worker until interrupted, or one bounded iteration."""
    args = _parser().parse_args()
    run(_run_worker(once=args.once))


if __name__ == "__main__":
    main()
