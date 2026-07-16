"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from xxx_api import __version__
from xxx_api.config import Settings, get_settings
from xxx_api.database import create_database_engine, create_session_factory
from xxx_api.email import SmtpEmailSender
from xxx_api.http import AuthResponseSecurityMiddleware, RequestContextMiddleware
from xxx_api.logging import configure_logging
from xxx_api.rate_limit import RedisRateLimiter
from xxx_api.routes.auth import router as auth_router
from xxx_api.routes.health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Release shared network and database resources on process shutdown."""
    yield
    await app.state.redis.aclose()
    await app.state.database_engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an application from validated settings."""
    runtime_settings = settings or get_settings()
    configure_logging(runtime_settings.log_level)
    app = FastAPI(
        title=runtime_settings.app_name,
        version=__version__,
        debug=runtime_settings.debug,
        docs_url="/docs" if runtime_settings.environment != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = runtime_settings
    database_engine = create_database_engine(runtime_settings)
    app.state.database_engine = database_engine
    app.state.session_factory = create_session_factory(database_engine)
    redis_client = Redis.from_url(
        runtime_settings.redis_url,
        socket_timeout=runtime_settings.redis_socket_timeout_seconds,
        socket_connect_timeout=runtime_settings.redis_socket_timeout_seconds,
        decode_responses=True,
    )
    app.state.redis = redis_client
    app.state.rate_limiter = RedisRateLimiter(redis_client, runtime_settings)
    app.state.email_sender = SmtpEmailSender(runtime_settings)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(AuthResponseSecurityMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=runtime_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Accept", "Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
    )
    app.include_router(auth_router, prefix=runtime_settings.api_prefix)
    app.include_router(health_router)
    return app


app = create_app()
