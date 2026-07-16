"""JWT access tokens, opaque bearer tokens, and CSRF tokens."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import compare_digest
from hmac import new as new_hmac
from secrets import token_urlsafe
from typing import Any
from uuid import UUID, uuid4

import jwt
from jwt.exceptions import InvalidTokenError

from xxx_api.config import Settings
from xxx_api.domain.roles import Role

ACCESS_TOKEN_TYPE = "access"
REQUIRED_ACCESS_CLAIMS = [
    "iss",
    "aud",
    "sub",
    "sid",
    "role",
    "type",
    "jti",
    "iat",
    "nbf",
    "exp",
]


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    """Validated claims made available to authorization code."""

    user_id: UUID
    session_id: UUID
    role: Role
    jwt_id: UUID
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class OpaqueToken:
    """Raw bearer value returned once and its persisted digest."""

    raw: str
    digest: str


def issue_access_token(
    *,
    user_id: UUID,
    session_id: UUID,
    role: Role,
    settings: Settings,
    now: datetime | None = None,
) -> str:
    """Issue one short-lived access token with a complete claim contract."""
    issued_at = (now or datetime.now(UTC)).astimezone(UTC)
    expires_at = issued_at + timedelta(seconds=settings.access_token_ttl_seconds)
    payload: dict[str, Any] = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": str(user_id),
        "sid": str(session_id),
        "role": role.value,
        "type": ACCESS_TOKEN_TYPE,
        "jti": str(uuid4()),
        "iat": issued_at,
        "nbf": issued_at,
        "exp": expires_at,
    }
    return jwt.encode(
        payload,
        settings.jwt_signing_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str, settings: Settings) -> AccessTokenClaims:
    """Verify signature, algorithm, issuer, audience, lifetime, type, and identifiers."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_signing_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": REQUIRED_ACCESS_CLAIMS},
        )
        if payload["type"] != ACCESS_TOKEN_TYPE:
            raise InvalidTokenError("unexpected token type")
        return AccessTokenClaims(
            user_id=UUID(payload["sub"]),
            session_id=UUID(payload["sid"]),
            role=Role(payload["role"]),
            jwt_id=UUID(payload["jti"]),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )
    except (InvalidTokenError, KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid access token") from error


def digest_opaque_token(raw_token: str, settings: Settings) -> str:
    """Create a keyed digest so database contents cannot validate token guesses."""
    return new_hmac(
        settings.token_hash_secret.get_secret_value().encode("utf-8"),
        raw_token.encode("utf-8"),
        sha256,
    ).hexdigest()


def issue_opaque_token(settings: Settings) -> OpaqueToken:
    """Generate a 256-bit URL-safe bearer token and its persisted digest."""
    raw = token_urlsafe(32)
    return OpaqueToken(raw=raw, digest=digest_opaque_token(raw, settings))


def verify_opaque_token(raw_token: str, expected_digest: str, settings: Settings) -> bool:
    """Compare opaque-token digests in constant time."""
    actual_digest = digest_opaque_token(raw_token, settings)
    return compare_digest(actual_digest, expected_digest)


def issue_csrf_token() -> str:
    """Generate an independent anti-forgery token."""
    return token_urlsafe(32)


def verify_csrf_token(cookie_value: str, header_value: str) -> bool:
    """Require non-empty, constant-time equality for double-submit CSRF tokens."""
    return bool(cookie_value and header_value) and compare_digest(cookie_value, header_value)
