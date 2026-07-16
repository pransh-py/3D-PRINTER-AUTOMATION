"""FastAPI dependencies for runtime adapters and authenticated principals."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from xxx_api.config import Settings
from xxx_api.database import get_session
from xxx_api.email import EmailSender
from xxx_api.models.identity import User
from xxx_api.rate_limit import RateLimiter
from xxx_api.security.cookies import session_cookie_names
from xxx_api.services.auth import InvalidSessionError, authenticate_access_token

DatabaseSession = Annotated[AsyncSession, Depends(get_session)]


def get_runtime_settings(request: Request) -> Settings:
    """Use the settings object that created this application instance."""
    return request.app.state.settings


def get_email_sender(request: Request) -> EmailSender:
    """Return the application-lifetime transactional email adapter."""
    return request.app.state.email_sender


def get_rate_limiter(request: Request) -> RateLimiter:
    """Return the application-lifetime distributed rate limiter."""
    return request.app.state.rate_limiter


def require_trusted_origin(
    request: Request,
    settings: Annotated[Settings, Depends(get_runtime_settings)],
) -> None:
    """Reject browser state changes that do not originate from the reviewed web origins."""
    origin = request.headers.get("Origin")
    if origin is None or origin not in settings.allowed_origins:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Untrusted origin")
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Untrusted origin")


async def get_current_user(
    request: Request,
    session: DatabaseSession,
    settings: Annotated[Settings, Depends(get_runtime_settings)],
) -> User:
    """Authenticate the access cookie against JWT and current database state."""
    names = session_cookie_names(settings)
    raw_token = request.cookies.get(names.access)
    if raw_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        return await authenticate_access_token(
            session,
            settings,
            raw_token=raw_token,
        )
    except InvalidSessionError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        ) from error


CurrentUser = Annotated[User, Depends(get_current_user)]
