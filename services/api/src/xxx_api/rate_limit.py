"""Distributed, privacy-preserving authentication rate limits."""

from dataclasses import dataclass
from typing import Protocol, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from xxx_api.config import Settings
from xxx_api.security.tokens import digest_opaque_token

RATE_LIMIT_SCRIPT = """
local retry_after = 0
for index, key in ipairs(KEYS) do
    local limit = tonumber(ARGV[(index - 1) * 2 + 1])
    local window = tonumber(ARGV[(index - 1) * 2 + 2])
    local current = redis.call('INCR', key)
    if current == 1 then
        redis.call('EXPIRE', key, window)
    end
    if current > limit then
        local ttl = redis.call('TTL', key)
        if ttl > retry_after then
            retry_after = ttl
        end
    end
end
return retry_after
"""


class RateLimitExceededError(Exception):
    """One or more layered authentication limits were exceeded."""

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, retry_after_seconds)
        super().__init__("rate limit exceeded")


class RateLimitUnavailableError(Exception):
    """The shared limiter could not make a fail-closed decision."""


@dataclass(frozen=True, slots=True)
class RateLimitRule:
    """One private identifier and its permitted request window."""

    identifier: str
    limit: int
    window_seconds: int


class RateLimiter(Protocol):
    """Shared limiter contract used by HTTP adapters and test fakes."""

    async def enforce(self, scope: str, rules: tuple[RateLimitRule, ...]) -> None:
        """Raise when a request must be throttled or cannot be checked."""


class RedisRateLimiter:
    """Enforce layered fixed-window counters atomically in Redis."""

    def __init__(self, client: Redis, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    async def enforce(self, scope: str, rules: tuple[RateLimitRule, ...]) -> None:
        keys: list[str] = []
        arguments: list[int] = []
        for rule in rules:
            if rule.limit < 1 or rule.window_seconds < 1:
                raise ValueError("rate-limit values must be positive")
            private_identifier = digest_opaque_token(
                f"rate:{scope}:{rule.identifier}",
                self._settings,
            )
            keys.append(f"xxx:rate:{scope}:{private_identifier}")
            arguments.extend((rule.limit, rule.window_seconds))

        try:
            result = await self._client.eval(
                RATE_LIMIT_SCRIPT,
                len(keys),
                *keys,
                *arguments,
            )
        except (RedisError, TimeoutError) as error:
            raise RateLimitUnavailableError from error

        retry_after = cast(int, result)
        if retry_after > 0:
            raise RateLimitExceededError(retry_after)
