"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from xxx_api import __version__
from xxx_api.config import Settings, get_settings
from xxx_api.http import RequestContextMiddleware
from xxx_api.logging import configure_logging
from xxx_api.routes.health import router as health_router


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
    )
    app.state.settings = runtime_settings
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=runtime_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Accept", "Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
    )
    app.include_router(health_router)
    return app


app = create_app()
