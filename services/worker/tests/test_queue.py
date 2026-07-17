"""Redis Stream adapter contract tests without an external Redis process."""

from asyncio import run
from typing import cast
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from xxx_worker.queue import AnalysisQueue


class FakeRedis:
    def __init__(self) -> None:
        self.group_busy = False
        self.new_messages: list[object] = []
        self.claimed_messages: object = ("0-0", [], [])
        self.published: list[tuple[str, dict[str, str]]] = []
        self.acknowledged: list[tuple[str, str, str]] = []

    async def xgroup_create(self, **_kwargs: object) -> bool:
        if self.group_busy:
            raise ResponseError("BUSYGROUP Consumer Group name already exists")
        return True

    async def xadd(self, stream: str, fields: dict[str, str]) -> bytes:
        self.published.append((stream, fields))
        return b"1-0"

    async def xreadgroup(self, **_kwargs: object) -> list[object]:
        return self.new_messages

    async def xautoclaim(self, **_kwargs: object) -> object:
        return self.claimed_messages

    async def xack(self, stream: str, group: str, message_id: str) -> int:
        self.acknowledged.append((stream, group, message_id))
        return 1


def _queue(fake: FakeRedis) -> AnalysisQueue:
    return AnalysisQueue(
        cast(Redis, fake),
        stream="xxx:analysis",
        group="workers",
        consumer="worker-1",
    )


def test_publish_read_and_acknowledge_use_identifier_only_contract() -> None:
    async def scenario() -> None:
        fake = FakeRedis()
        queue = _queue(fake)
        event_id = uuid4()
        run_id = uuid4()
        stream_id = await queue.publish(event_id=event_id, run_id=run_id)
        assert stream_id == "1-0"
        assert fake.published == [
            (
                "xxx:analysis",
                {
                    "outbox_event_id": str(event_id),
                    "analysis_run_id": str(run_id),
                },
            )
        ]
        fake.new_messages = [
            (
                b"xxx:analysis",
                [
                    (
                        b"1-0",
                        {
                            b"outbox_event_id": str(event_id).encode(),
                            b"analysis_run_id": str(run_id).encode(),
                        },
                    )
                ],
            )
        ]
        message = await queue.read_new()
        assert message is not None
        assert message.outbox_event_id == event_id
        assert message.analysis_run_id == run_id
        await queue.acknowledge(message)
        assert fake.acknowledged == [("xxx:analysis", "workers", "1-0")]

    run(scenario())


def test_existing_group_is_idempotent_and_stale_message_is_reclaimed() -> None:
    async def scenario() -> None:
        fake = FakeRedis()
        fake.group_busy = True
        queue = _queue(fake)
        await queue.ensure_group()
        event_id = uuid4()
        run_id = uuid4()
        fake.claimed_messages = (
            b"2-0",
            [
                (
                    b"1-0",
                    {
                        b"outbox_event_id": str(event_id).encode(),
                        b"analysis_run_id": str(run_id).encode(),
                    },
                )
            ],
            [],
        )
        message = await queue.reclaim_stale(minimum_idle_ms=600_000)
        assert message is not None
        assert message.stream_id == "1-0"
        assert message.analysis_run_id == run_id

    run(scenario())
