"""FastAPI dependencies for runtime adapters and authenticated principals."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xxx_api.config import Settings
from xxx_api.database import get_session
from xxx_api.domain.roles import Role
from xxx_api.email import EmailSender
from xxx_api.models.identity import MfaMethod, User
from xxx_api.rate_limit import RateLimiter
from xxx_api.security.cookies import session_cookie_names
from xxx_api.security.tokens import verify_csrf_token
from xxx_api.services.auth import (
    AuthenticatedPrincipal,
    InvalidSessionError,
    authenticate_access_principal,
)
from xxx_api.storage import ObjectStorage

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


def get_object_storage(request: Request) -> ObjectStorage:
    """Return the process-owned private object-storage adapter."""
    return request.app.state.object_storage


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


async def get_current_principal(
    request: Request,
    session: DatabaseSession,
    settings: Annotated[Settings, Depends(get_runtime_settings)],
) -> AuthenticatedPrincipal:
    """Authenticate the access cookie against JWT and persisted session state."""
    names = session_cookie_names(settings)
    raw_token = request.cookies.get(names.access)
    if raw_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        return await authenticate_access_principal(
            session,
            settings,
            raw_token=raw_token,
        )
    except InvalidSessionError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        ) from error


CurrentPrincipal = Annotated[AuthenticatedPrincipal, Depends(get_current_principal)]


async def get_current_user(principal: CurrentPrincipal) -> User:
    """Expose the validated user for routes that do not need session evidence."""
    return principal.user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_owner(principal: CurrentPrincipal) -> AuthenticatedPrincipal:
    """Deny every identity except the active database-bound primary owner."""
    user = principal.user
    if user.role is not Role.OWNER or user.owner_slot != "primary":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner access required")
    return principal


OwnerPrincipal = Annotated[AuthenticatedPrincipal, Depends(require_owner)]


async def require_session_csrf(
    request: Request,
    principal: CurrentPrincipal,
    settings: Annotated[Settings, Depends(get_runtime_settings)],
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    """Require a signed double-submit proof bound to the authenticated session."""
    names = session_cookie_names(settings)
    csrf_cookie = request.cookies.get(names.csrf, "")
    if not verify_csrf_token(
        csrf_cookie,
        csrf_header or "",
        principal.refresh_session.id,
        settings,
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


SessionCsrf = Annotated[None, Depends(require_session_csrf)]


async def require_recent_owner_mfa(
    principal: OwnerPrincipal,
    session: DatabaseSession,
    settings: Annotated[Settings, Depends(get_runtime_settings)],
) -> AuthenticatedPrincipal:
    """Require enabled MFA and recent MFA proof on this exact owner session."""
    enabled_at = await session.scalar(
        select(MfaMethod.enabled_at).where(MfaMethod.user_id == principal.user.id)
    )
    mfa_at = principal.refresh_session.mfa_authenticated_at
    if enabled_at is None or mfa_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Recent owner MFA required",
        )
    if mfa_at.tzinfo is None:
        mfa_at = mfa_at.replace(tzinfo=UTC)
    if mfa_at < datetime.now(UTC) - timedelta(seconds=settings.recent_owner_mfa_ttl_seconds):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Recent owner MFA required",
        )
    return principal


RecentMfaOwnerPrincipal = Annotated[AuthenticatedPrincipal, Depends(require_recent_owner_mfa)]
