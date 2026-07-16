"""Async SQLAlchemy engine and request-scoped session management."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from starlette.requests import Request

from xxx_api.config import Settings


def create_database_engine(settings: Settings) -> AsyncEngine:
    """Create the connection pool owned by one application instance."""
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create sessions that do not share mutable transaction state."""
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield one database session for one request/task."""
    async with request.app.state.session_factory() as session:
        yield session
