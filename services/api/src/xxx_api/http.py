"""HTTP middleware shared by the API."""

import logging
from time import perf_counter
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("xxx_api.request")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a safe correlation ID to every request and response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = perf_counter()
        supplied = request.headers.get("X-Request-ID", "")
        request_id = supplied if self._is_safe_request_id(supplied) else uuid4().hex
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request failed",
                extra={
                    "event": "request.failed",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                },
            )
            raise
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request completed",
            extra={
                "event": "request.completed",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((perf_counter() - started) * 1000, 2),
            },
        )
        return response

    @staticmethod
    def _is_safe_request_id(value: str) -> bool:
        return bool(value) and len(value) <= 64 and all(
            character.isalnum() or character in "-_" for character in value
        )


class AuthResponseSecurityMiddleware(BaseHTTPMiddleware):
    """Prevent storage of authentication responses and reduce browser ambiguity."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        api_prefix = request.app.state.settings.api_prefix
        if request.url.path.startswith(f"{api_prefix}/auth"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
        return response
