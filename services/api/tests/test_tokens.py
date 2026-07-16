"""Access, opaque, and CSRF token tests."""

from datetime import UTC, datetime
from uuid import uuid4

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


def test_opaque_token_digest_is_keyed_and_verifiable() -> None:
    settings = Settings(environment="test")
    token = issue_opaque_token(settings)

    assert token.raw != token.digest
    assert token.digest == digest_opaque_token(token.raw, settings)
    assert verify_opaque_token(token.raw, token.digest, settings)
    assert not verify_opaque_token(f"{token.raw}x", token.digest, settings)


def test_csrf_token_requires_exact_non_empty_match() -> None:
    token = issue_csrf_token()

    assert verify_csrf_token(token, token)
    assert not verify_csrf_token(token, f"{token}x")
    assert not verify_csrf_token("", "")
