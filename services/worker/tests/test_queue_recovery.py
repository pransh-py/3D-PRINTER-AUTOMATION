"""A transient Redis disconnect must not permanently strand customer slicing."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from redis.exceptions import ResponseError, TimeoutError
from xxx_api.config import Settings

from xxx_worker.main import consume_analysis
from xxx_worker.orchestrator import DeliveryDisposition


@pytest.mark.parametrize("error", [TimeoutError(), ResponseError("NOGROUP missing")])
def test_transient_queue_failure_resumes_without_acknowledging_unprocessed_work(error):
    async def scenario():
        queue = AsyncMock()
        queue.ensure_group.side_effect = [error, None]
        queue.reclaim_stale.return_value = None
        message = object()
        queue.read_new.return_value = message
        processor = AsyncMock()
        processor.process.return_value = DeliveryDisposition.ACKNOWLEDGE
        with (
            patch("xxx_worker.main.dispatch_analysis_outbox", new=AsyncMock()),
            patch("xxx_worker.main.sleep", new=AsyncMock()),
        ):
            assert (
                await consume_analysis(
                    queue, None, processor, Settings(environment="test"), once=False
                )
                is None
            )
            queue.acknowledge.assert_not_called()
            assert (
                await consume_analysis(
                    queue, None, processor, Settings(environment="test"), once=False
                )
                is message
            )
            queue.acknowledge.assert_awaited_once_with(message)

    asyncio.run(scenario())


def test_unexpected_redis_error_still_surfaces():
    async def scenario():
        queue = AsyncMock()
        queue.ensure_group.side_effect = ResponseError("WRONGTYPE corrupt stream")
        with pytest.raises(ResponseError):
            await consume_analysis(
                queue, None, AsyncMock(), Settings(environment="test"), once=False
            )

    asyncio.run(scenario())
