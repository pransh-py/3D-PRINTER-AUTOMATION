"""Private Redis Stream transport for at-least-once analysis delivery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import ResponseError


class AnalysisQueueMessageError(Exception):
    """A private queue message does not match the fixed internal contract."""


@dataclass(frozen=True, slots=True)
class AnalysisQueueMessage:
    """One parsed stream delivery containing identifiers only."""

    stream_id: str
    outbox_event_id: UUID
    analysis_run_id: UUID


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict")
    if isinstance(value, str):
        return value
    raise AnalysisQueueMessageError("queue field is not text")


def _message(stream_id: object, fields: object) -> AnalysisQueueMessage:
    if not isinstance(fields, dict):
        raise AnalysisQueueMessageError("queue fields are invalid")
    normalized = {_text(key): _text(value) for key, value in fields.items()}
    if set(normalized) != {"outbox_event_id", "analysis_run_id"}:
        raise AnalysisQueueMessageError("queue fields do not match the contract")
    try:
        return AnalysisQueueMessage(
            stream_id=_text(stream_id),
            outbox_event_id=UUID(normalized["outbox_event_id"]),
            analysis_run_id=UUID(normalized["analysis_run_id"]),
        )
    except ValueError as error:
        raise AnalysisQueueMessageError("queue identifier is invalid") from error


class AnalysisQueue:
    """Small typed adapter over one private Redis Stream consumer group."""

    def __init__(self, redis: Redis, *, stream: str, group: str, consumer: str) -> None:
        self._redis = redis
        self._stream = stream
        self._group = group
        self._consumer = consumer

    async def ensure_group(self) -> None:
        """Create the consumer group and stream once without resetting progress."""
        try:
            await self._redis.xgroup_create(
                name=self._stream,
                groupname=self._group,
                id="0-0",
                mkstream=True,
            )
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise

    async def publish(self, *, event_id: UUID, run_id: UUID) -> str:
        """Publish only stable identifiers; database rows hold the full contract."""
        result = await self._redis.xadd(
            self._stream,
            {
                "outbox_event_id": str(event_id),
                "analysis_run_id": str(run_id),
            },
        )
        return _text(result)

    async def read_new(self, *, block_ms: int = 1_000) -> AnalysisQueueMessage | None:
        """Read one never-delivered entry for this consumer group."""
        raw = await self._redis.xreadgroup(
            groupname=self._group,
            consumername=self._consumer,
            streams={self._stream: ">"},
            count=1,
            block=block_ms,
        )
        streams = cast(list[tuple[object, list[tuple[object, object]]]], raw)
        if not streams or not streams[0][1]:
            return None
        stream_id, fields = streams[0][1][0]
        return _message(stream_id, fields)

    async def reclaim_stale(self, *, minimum_idle_ms: int) -> AnalysisQueueMessage | None:
        """Claim one unacknowledged entry after its worker lease can no longer be valid."""
        raw = await self._redis.xautoclaim(
            name=self._stream,
            groupname=self._group,
            consumername=self._consumer,
            min_idle_time=minimum_idle_ms,
            start_id="0-0",
            count=1,
        )
        claimed = cast(tuple[object, list[tuple[object, object]], object], raw)
        if len(claimed) < 2 or not claimed[1]:
            return None
        stream_id, fields = claimed[1][0]
        return _message(stream_id, fields)

    async def acknowledge(self, message: AnalysisQueueMessage) -> None:
        """Acknowledge only after the database transition is durably terminal."""
        await self._redis.xack(self._stream, self._group, message.stream_id)
