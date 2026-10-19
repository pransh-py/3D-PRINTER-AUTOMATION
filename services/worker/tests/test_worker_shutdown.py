"""Background-task errors remain visible while all cleanup hooks are reached."""

import asyncio

from worker_shutdown_lab import reproduce_notice_failure
from xxx_api.config import Settings

from xxx_worker.main import QUEUE_BLOCK_MS, create_worker_redis


def test_worker_network_timeout_outlasts_the_idle_block():
    client = create_worker_redis(Settings(_env_file=None, environment="test"))
    assert client.connection_pool.connection_kwargs["socket_timeout"] > QUEUE_BLOCK_MS / 1000
    asyncio.run(client.aclose())


def test_notice_schema_failure_does_not_skip_connection_cleanup():
    report = asyncio.run(reproduce_notice_failure())
    assert all(report["workerCleanupHooksReached"].values())
