"""Session-cookie names, attributes, issuance, and deletion."""

from dataclasses import dataclass
from datetime import UTC, datetime

from starlette.responses import Response

from xxx_api.config import Settings
from xxx_api.services.auth import SessionIssue


@dataclass(frozen=True, slots=True)
class SessionCookieNames:
    """Environment-appropriate host-only cookie names."""

    access: str
    refresh: str
    csrf: str


def session_cookie_names(settings: Settings) -> SessionCookieNames:
    """Use hardened prefixes only when production cookie requirements are met."""
    if settings.secure_cookies:
        return SessionCookieNames(
            access="__Host-xxx_access",
            refresh="__Secure-xxx_refresh",
            csrf="__Host-xxx_csrf",
        )
    return SessionCookieNames(
        access="xxx_access",
        refresh="xxx_refresh",
        csrf="xxx_csrf",
    )


def set_session_cookies(
    response: Response,
    issue: SessionIssue,
    settings: Settings,
) -> None:
    """Place bearer tokens only in scoped cookies, never a response body."""
    names = session_cookie_names(settings)
    refresh_max_age = max(
        0,
        int((issue.refresh_expires_at - datetime.now(UTC)).total_seconds()),
    )
    response.set_cookie(
        names.access,
        issue.access_token,
        max_age=settings.access_token_ttl_seconds,
        path="/",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        names.refresh,
        issue.refresh_token,
        max_age=refresh_max_age,
        path=f"{settings.api_prefix}/auth",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="strict",
    )
    response.set_cookie(
        names.csrf,
        issue.csrf_token,
        max_age=refresh_max_age,
        path="/",
        secure=settings.secure_cookies,
        httponly=False,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def clear_session_cookies(response: Response, settings: Settings) -> None:
    """Expire all session cookies using their original names and paths."""
    names = session_cookie_names(settings)
    response.delete_cookie(
        names.access,
        path="/",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        names.refresh,
        path=f"{settings.api_prefix}/auth",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        names.csrf,
        path="/",
        secure=settings.secure_cookies,
        httponly=False,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
