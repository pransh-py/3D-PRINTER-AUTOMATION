"""Distributed rate-limit privacy and decision tests."""

from asyncio import run
from typing import Any, cast

import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError

from xxx_api.config import Settings
from xxx_api.rate_limit import (
    RateLimitExceededError,
    RateLimitRule,
    RateLimitUnavailableError,
    RedisRateLimiter,
)


class FakeRedis:
    """Return a configured Lua result and capture only command inputs."""

    def __init__(self, result: int) -> None:
        self.result = result
        self.arguments: tuple[Any, ...] = ()

    async def eval(self, *arguments: Any) -> int:
        self.arguments = arguments
        return self.result


class UnavailableRedis:
    async def eval(self, *arguments: Any) -> int:
        raise RedisError


def test_rate_limit_keys_do_not_contain_private_identifiers() -> None:
    fake = FakeRedis(result=0)
    limiter = RedisRateLimiter(cast(Redis, fake), Settings(environment="test"))

    run(
        limiter.enforce(
            "login",
            (
                RateLimitRule("buyer@example.com", limit=5, window_seconds=900),
                RateLimitRule("127.0.0.1", limit=10, window_seconds=900),
            ),
        )
    )

    serialized = repr(fake.arguments)
    assert "buyer@example.com" not in serialized
    assert "127.0.0.1" not in serialized
    assert "xxx:rate:login:" in serialized


def test_rate_limit_reports_redis_retry_after() -> None:
    fake = FakeRedis(result=17)
    limiter = RedisRateLimiter(cast(Redis, fake), Settings(environment="test"))

    with pytest.raises(RateLimitExceededError) as captured:
        run(
            limiter.enforce(
                "login",
                (RateLimitRule("buyer@example.com", limit=5, window_seconds=900),),
            )
        )

    assert captured.value.retry_after_seconds == 17


def test_rate_limit_fails_closed_when_redis_is_unavailable() -> None:
    limiter = RedisRateLimiter(
        cast(Redis, UnavailableRedis()),
        Settings(environment="test"),
    )

    with pytest.raises(RateLimitUnavailableError):
        run(
            limiter.enforce(
                "login",
                (RateLimitRule("buyer@example.com", limit=5, window_seconds=900),),
            )
        )
