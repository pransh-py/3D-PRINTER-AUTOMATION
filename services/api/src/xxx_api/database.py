"""Async SQLAlchemy engine and request-scoped session management."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from xxx_api.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Create one connection pool per API process."""
    settings = get_settings()
    return create_async_engine(settings.database_url, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create sessions that do not share mutable transaction state."""
    return async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield one database session for one request/task."""
    async with get_session_factory()() as session:
        yield session


async def dispose_engine() -> None:
    """Close pooled connections during application shutdown."""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    get_session_factory.cache_clear()
    get_engine.cache_clear()
