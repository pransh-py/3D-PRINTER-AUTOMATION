"""Access, opaque, and CSRF token tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from xxx_api.config import Settings
from xxx_api.domain.roles import Role
from xxx_api.security.tokens import (
    decode_access_token,
    digest_opaque_token,
    issue_access_token,
    issue_csrf_token,
    issue_opaque_token,
    verify_csrf_token,
    verify_opaque_token,
)


def test_access_token_round_trip() -> None:
    settings = Settings(environment="test")
    user_id = uuid4()
    session_id = uuid4()
    now = datetime.now(UTC)

    token = issue_access_token(
        user_id=user_id,
        session_id=session_id,
        role=Role.BUYER,
        settings=settings,
        now=now,
    )
    claims = decode_access_token(token, settings)

    assert claims.user_id == user_id
    assert claims.session_id == session_id
    assert claims.role is Role.BUYER
    assert claims.issued_at.timestamp() == int(now.timestamp())
    assert claims.expires_at.timestamp() == int(now.timestamp()) + 900


def test_access_token_rejects_wrong_audience() -> None:
    issuer = Settings(environment="test", jwt_audience="one-audience")
    verifier = Settings(environment="test", jwt_audience="another-audience")
    token = issue_access_token(
        user_id=uuid4(),
        session_id=uuid4(),
        role=Role.BUYER,
        settings=issuer,
    )

    with pytest.raises(ValueError, match="invalid access token"):
        decode_access_token(token, verifier)


@pytest.mark.parametrize("invalid_claim", ["expired", "issuer", "signature", "algorithm", "nbf"])
def test_claim_checks_stay_enabled_across_repeated_decodes(invalid_claim: str) -> None:
    settings = Settings(environment="test")
    valid = issue_access_token(
        user_id=uuid4(), session_id=uuid4(), role=Role.BUYER, settings=settings
    )
    claims = jwt.decode(
        valid,
        settings.jwt_signing_secret.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )
    secret = settings.jwt_signing_secret.get_secret_value()
    algorithm = settings.jwt_algorithm
    if invalid_claim == "expired":
        claims["exp"] = int((datetime.now(UTC) - timedelta(hours=1)).timestamp())
    elif invalid_claim == "issuer":
        claims["iss"] = "untrusted-issuer"
    elif invalid_claim == "signature":
        secret = "untrusted-signing-key-at-least-thirty-two-bytes"
    elif invalid_claim == "algorithm":
        algorithm = "HS384"
    else:
        claims["nbf"] = int((datetime.now(UTC) + timedelta(hours=1)).timestamp())
    invalid = jwt.encode(claims, secret, algorithm=algorithm)
    for _ in range(2):
        decode_access_token(valid, settings)
        with pytest.raises(ValueError, match="invalid access token"):
            decode_access_token(invalid, settings)


def test_opaque_token_digest_is_keyed_and_verifiable() -> None:
    settings = Settings(environment="test")
    token = issue_opaque_token(settings)

    assert token.raw != token.digest
    assert token.digest == digest_opaque_token(token.raw, settings)
    assert verify_opaque_token(token.raw, token.digest, settings)
    assert not verify_opaque_token(f"{token.raw}x", token.digest, settings)


def test_csrf_token_requires_exact_non_empty_match() -> None:
    settings = Settings(environment="test")
    session_id = uuid4()
    token = issue_csrf_token(session_id, settings)

    assert verify_csrf_token(token, token, session_id, settings)
    assert not verify_csrf_token(token, f"{token}x", session_id, settings)
    assert not verify_csrf_token(token, token, uuid4(), settings)
    assert not verify_csrf_token("", "", session_id, settings)
