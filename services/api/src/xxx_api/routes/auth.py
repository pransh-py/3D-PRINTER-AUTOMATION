"""Public buyer identity and session HTTP adapters."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from xxx_api.config import Settings
from xxx_api.dependencies import (
    CurrentUser,
    DatabaseSession,
    get_email_sender,
    get_rate_limiter,
    get_runtime_settings,
    require_trusted_origin,
)
from xxx_api.email import EmailDeliveryError, EmailSender
from xxx_api.rate_limit import (
    RateLimiter,
    RateLimitExceededError,
    RateLimitRule,
    RateLimitUnavailableError,
)
from xxx_api.schemas.auth import (
    AuthenticatedUserResponse,
    EmailRequest,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    ResetPasswordRequest,
    TokenRequest,
)
from xxx_api.security.cookies import (
    clear_session_cookies,
    session_cookie_names,
    set_session_cookies,
)
from xxx_api.security.email import normalize_email
from xxx_api.services.auth import (
    InvalidCredentialsError,
    InvalidCsrfTokenError,
    InvalidOneTimeTokenError,
    InvalidSessionError,
    RefreshTokenReuseError,
    VerificationRequiredError,
    issue_email_verification,
    login,
    logout,
    register_buyer,
    request_password_reset,
    reset_password,
    rotate_refresh_token,
    verify_email,
)

router = APIRouter(prefix="/auth", tags=["identity"])
logger = logging.getLogger("xxx_api.identity")
TrustedOrigin = Annotated[None, Depends(require_trusted_origin)]
RuntimeSettings = Annotated[Settings, Depends(get_runtime_settings)]
EmailAdapter = Annotated[EmailSender, Depends(get_email_sender)]
Limiter = Annotated[RateLimiter, Depends(get_rate_limiter)]

GENERIC_ACCOUNT_MESSAGE = "If the account is eligible, instructions will be sent."


def _client_identifier(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _record_delivery_failure(request: Request, message_kind: str) -> None:
    """Record an operational failure without recipient, token, or provider details."""
    logger.error(
        "transactional email delivery failed",
        extra={
            "event": "identity.email_delivery_failed",
            "request_id": getattr(request.state, "request_id", "unknown"),
            "message_kind": message_kind,
        },
    )


async def _enforce(
    limiter: RateLimiter,
    scope: str,
    rules: tuple[RateLimitRule, ...],
) -> None:
    try:
        await limiter.enforce(scope, rules)
    except RateLimitExceededError as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    except RateLimitUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from error


def _email_rules(request: Request, email: str, *, email_limit: int) -> tuple[RateLimitRule, ...]:
    return (
        RateLimitRule(_client_identifier(request), limit=10, window_seconds=15 * 60),
        RateLimitRule(email, limit=email_limit, window_seconds=60 * 60),
    )


def _token_rules(request: Request, token: str, *, limit: int = 10) -> tuple[RateLimitRule, ...]:
    return (
        RateLimitRule(_client_identifier(request), limit=20, window_seconds=15 * 60),
        RateLimitRule(token, limit=limit, window_seconds=15 * 60),
    )


@router.post(
    "/register",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def register(
    payload: RegisterRequest,
    request: Request,
    _origin: TrustedOrigin,
    session: DatabaseSession,
    settings: RuntimeSettings,
    sender: EmailAdapter,
    limiter: Limiter,
) -> MessageResponse:
    """Create only a public buyer identity and send its verification link."""
    email = normalize_email(str(payload.email))
    await _enforce(limiter, "register", _email_rules(request, email, email_limit=3))
    issue = await register_buyer(
        session,
        settings,
        email=email,
        display_name=payload.display_name,
        password=payload.password,
    )
    if issue is not None:
        try:
            await sender.send_verification(email, issue.verification_token)
        except EmailDeliveryError:
            _record_delivery_failure(request, "email_verification")
    return MessageResponse(message=GENERIC_ACCOUNT_MESSAGE)


@router.post(
    "/resend-verification",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resend_verification(
    payload: EmailRequest,
    request: Request,
    _origin: TrustedOrigin,
    session: DatabaseSession,
    settings: RuntimeSettings,
    sender: EmailAdapter,
    limiter: Limiter,
) -> MessageResponse:
    """Generically resend verification only for an eligible pending buyer."""
    email = normalize_email(str(payload.email))
    await _enforce(limiter, "resend-verification", _email_rules(request, email, email_limit=3))
    issue = await issue_email_verification(session, settings, email=email)
    if issue is not None:
        try:
            await sender.send_verification(email, issue.verification_token)
        except EmailDeliveryError:
            _record_delivery_failure(request, "email_verification")
    return MessageResponse(message=GENERIC_ACCOUNT_MESSAGE)


@router.post("/verify-email", response_model=MessageResponse)
async def activate_email(
    payload: TokenRequest,
    request: Request,
    _origin: TrustedOrigin,
    session: DatabaseSession,
    settings: RuntimeSettings,
    limiter: Limiter,
) -> MessageResponse:
    """Consume a one-time verification token without accepting it in a URL log."""
    await _enforce(limiter, "verify-email", _token_rules(request, payload.token))
    try:
        await verify_email(session, settings, raw_token=payload.token)
    except InvalidOneTimeTokenError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification link is invalid or expired",
        ) from error
    return MessageResponse(message="Email verified")


@router.post("/login", response_model=AuthenticatedUserResponse)
async def create_session(
    payload: LoginRequest,
    request: Request,
    response: Response,
    _origin: TrustedOrigin,
    session: DatabaseSession,
    settings: RuntimeSettings,
    limiter: Limiter,
) -> AuthenticatedUserResponse:
    """Authenticate credentials and place bearer values only in cookies."""
    email = normalize_email(str(payload.email))
    await _enforce(limiter, "login", _email_rules(request, email, email_limit=5))
    try:
        issue = await login(
            session,
            settings,
            email=email,
            password=payload.password,
            user_agent=request.headers.get("User-Agent"),
        )
    except InvalidCredentialsError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        ) from error
    except VerificationRequiredError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification required",
        ) from error
    set_session_cookies(response, issue, settings)
    return AuthenticatedUserResponse(
        id=issue.user_id,
        email=issue.email,
        displayName=issue.display_name,
        role=issue.role,
    )


@router.post("/refresh", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def refresh_session(
    request: Request,
    _origin: TrustedOrigin,
    session: DatabaseSession,
    settings: RuntimeSettings,
    limiter: Limiter,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> Response:
    """Rotate the refresh cookie after origin and session-bound CSRF checks."""
    names = session_cookie_names(settings)
    raw_refresh = request.cookies.get(names.refresh)
    csrf_cookie = request.cookies.get(names.csrf, "")
    if raw_refresh is None:
        invalid = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Session is invalid"},
        )
        clear_session_cookies(invalid, settings)
        return invalid
    await _enforce(limiter, "refresh", _token_rules(request, raw_refresh, limit=30))
    try:
        issue = await rotate_refresh_token(
            session,
            settings,
            raw_token=raw_refresh,
            csrf_cookie=csrf_cookie,
            csrf_header=csrf_header or "",
            user_agent=request.headers.get("User-Agent"),
        )
    except (InvalidSessionError, InvalidCsrfTokenError, RefreshTokenReuseError):
        invalid = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Session is invalid"},
        )
        clear_session_cookies(invalid, settings)
        return invalid
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_session_cookies(response, issue, settings)
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def destroy_session(
    request: Request,
    _origin: TrustedOrigin,
    session: DatabaseSession,
    settings: RuntimeSettings,
    limiter: Limiter,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> Response:
    """Revoke the refresh family and expire all browser session cookies."""
    names = session_cookie_names(settings)
    raw_refresh = request.cookies.get(names.refresh)
    csrf_cookie = request.cookies.get(names.csrf, "")
    if raw_refresh is not None:
        await _enforce(limiter, "logout", _token_rules(request, raw_refresh, limit=30))
        try:
            await logout(
                session,
                settings,
                raw_refresh_token=raw_refresh,
                csrf_cookie=csrf_cookie,
                csrf_header=csrf_header or "",
            )
        except InvalidCsrfTokenError as error:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid CSRF token",
            ) from error
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookies(response, settings)
    return response


@router.get("/me", response_model=AuthenticatedUserResponse)
async def current_user(user: CurrentUser) -> AuthenticatedUserResponse:
    """Return only the authenticated principal's safe profile fields."""
    return AuthenticatedUserResponse(
        id=user.id,
        email=user.email,
        displayName=user.display_name,
        role=user.role,
    )


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def forgot_password(
    payload: EmailRequest,
    request: Request,
    _origin: TrustedOrigin,
    session: DatabaseSession,
    settings: RuntimeSettings,
    sender: EmailAdapter,
    limiter: Limiter,
) -> MessageResponse:
    """Generically issue reset mail only for an eligible account."""
    email = normalize_email(str(payload.email))
    await _enforce(limiter, "forgot-password", _email_rules(request, email, email_limit=3))
    issue = await request_password_reset(session, settings, email=email)
    if issue is not None:
        try:
            await sender.send_password_reset(email, issue.reset_token)
        except EmailDeliveryError:
            _record_delivery_failure(request, "password_reset")
    return MessageResponse(message=GENERIC_ACCOUNT_MESSAGE)


@router.post("/reset-password", response_model=MessageResponse)
async def complete_password_reset(
    payload: ResetPasswordRequest,
    request: Request,
    _origin: TrustedOrigin,
    session: DatabaseSession,
    settings: RuntimeSettings,
    limiter: Limiter,
) -> MessageResponse:
    """Consume a reset token, change the password, and revoke every session."""
    await _enforce(limiter, "reset-password", _token_rules(request, payload.token))
    try:
        await reset_password(
            session,
            settings,
            raw_token=payload.token,
            new_password=payload.new_password,
        )
    except InvalidOneTimeTokenError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password reset link is invalid or expired",
        ) from error
    return MessageResponse(message="Password reset complete")
