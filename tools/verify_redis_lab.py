"""Real queue/recovery and atomic limiter checks in the named loopback-only Redis lab.

Never accepts an arbitrary URL. Fictional identifiers use a fresh namespace on each run;
no production key is deleted, no business state is changed, and no physical command exists.
"""

import asyncio
import json
from pathlib import Path
from socket import socket
from subprocess import run
from uuid import uuid4

from redis.asyncio import Redis

from xxx_api.config import Settings
from xxx_api.rate_limit import (
    RateLimitExceededError,
    RateLimitRule,
    RateLimitUnavailableError,
    RedisRateLimiter,
)
from xxx_worker.queue import AnalysisQueue

ROOT = Path(__file__).resolve().parents[1]
LAB_CONTAINER = "printflow-redis-lab-20261011"
LAB_IMAGE = "redis:8.8.0-alpine3.23"
LAB_URL = "redis://127.0.0.1:56379/0"


async def verify() -> None:
    result = run(
        ["docker", "inspect", LAB_CONTAINER], check=True, capture_output=True, text=True
    )
    container = json.loads(result.stdout)[0]
    assert container["Config"]["Image"] == LAB_IMAGE
    assert container["State"]["Running"] is True
    assert container["HostConfig"]["PortBindings"]["6379/tcp"] == [
        {"HostIp": "127.0.0.1", "HostPort": "56379"}
    ]
    namespace = f"lab-{uuid4().hex}"
    client = Redis.from_url(LAB_URL, socket_timeout=2, socket_connect_timeout=2)
    try:
        assert await client.ping()
        first = AnalysisQueue(
            client, stream=namespace, group="lab-workers", consumer="crashed-worker"
        )
        second = AnalysisQueue(
            client, stream=namespace, group="lab-workers", consumer="recovery-worker"
        )
        await first.ensure_group()
        await second.ensure_group()
        event_id, run_id = uuid4(), uuid4()
        stream_id = await first.publish(event_id=event_id, run_id=run_id)
        message = await first.read_new(block_ms=1)
        assert message and message.stream_id == stream_id
        assert message.outbox_event_id == event_id and message.analysis_run_id == run_id
        # Force eligibility in this transport-only test, not a production worker lease timeout.
        recovered = await second.reclaim_stale(minimum_idle_ms=0)
        assert recovered == message
        await second.acknowledge(recovered)
        assert (await client.xpending(namespace, "lab-workers"))["pending"] == 0
        assert await second.read_new(block_ms=1) is None
        entries = await client.xrange(namespace)
        assert entries and entries[0][1] is not None
        fields = entries[0][1]
        assert set(fields) == {b"outbox_event_id", b"analysis_run_id"}

        settings = Settings(_env_file=None, environment="test", redis_url=LAB_URL)
        limiter = RedisRateLimiter(client, settings)
        rules = (RateLimitRule("fictional@lab.example", limit=3, window_seconds=60),)

        async def limited_request() -> bool:
            try:
                await limiter.enforce(namespace, rules)
            except RateLimitExceededError as error:
                assert 1 <= error.retry_after_seconds <= 60
                return False
            return True

        allowed = await asyncio.gather(*(limited_request() for _ in range(10)))
        assert sum(allowed) == 3
        keys = [key async for key in client.scan_iter(match=f"xxx:rate:{namespace}:*")]
        assert len(keys) == 1 and b"fictional@lab.example" not in keys[0]
        assert 0 < await client.ttl(keys[0]) <= 60

        # An unused loopback port exercises a genuine connection refusal without
        # stopping Redis or mutating authentication on any shared service.
        with socket() as probe:
            probe.settimeout(1)
            assert probe.connect_ex(("127.0.0.1", 56380)) != 0, "failure port is in use"
        broken = Redis.from_url(
            "redis://127.0.0.1:56380/0", socket_timeout=1, socket_connect_timeout=1
        )
        try:
            try:
                await RedisRateLimiter(broken, settings).enforce(namespace, rules)
            except RateLimitUnavailableError:
                pass
            else:
                raise AssertionError("the real failed broker must refuse the request")
        finally:
            await broken.aclose()

        report = {
            "labOnly": True,
            "service": LAB_IMAGE,
            "queueTransport": "real Redis Stream",
            "messageFields": "identifiers only",
            "reclaimedAndAcknowledged": True,
            "pendingAfterAcknowledgement": 0,
            "simultaneousLimiterRequests": 10,
            "permitted": sum(allowed),
            "throttled": len(allowed) - sum(allowed),
            "limiterBackendFailure": "failed closed",
            "physicalPrinterCommands": 0,
            "businessDatabaseTouched": False,
        }
        directory = ROOT / ".local/workflow"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "redis-lab.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(verify())
