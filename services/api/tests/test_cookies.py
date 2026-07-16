"""Session-cookie hardening tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from starlette.responses import Response

from xxx_api.config import Settings
from xxx_api.domain.roles import Role
from xxx_api.security.cookies import set_session_cookies
from xxx_api.services.auth import SessionIssue


def test_production_cookies_use_secure_prefixes_and_scopes() -> None:
    settings = Settings(
        environment="production",
        allowed_origins=["https://example.com"],
        secure_cookies=True,
        jwt_signing_secret="production-jwt-signing-secret-1234567890",
        token_hash_secret="production-token-hash-secret-0987654321",
        public_web_url="https://example.com",
        email_sender_address="no-reply@example.org",
        smtp_host="smtp.example.org",
        smtp_port=587,
        smtp_starttls=True,
    )
    now = datetime.now(UTC)
    issue = SessionIssue(
        user_id=uuid4(),
        email="buyer@example.com",
        display_name="Buyer",
        role=Role.BUYER,
        access_token="access-bearer",
        refresh_token="refresh-bearer",
        csrf_token="csrf-proof",
        access_expires_at=now + timedelta(minutes=15),
        refresh_expires_at=now + timedelta(days=30),
    )
    response = Response()

    set_session_cookies(response, issue, settings)

    cookies = response.headers.getlist("set-cookie")
    assert any(
        value.startswith("__Host-xxx_access=")
        and "HttpOnly" in value
        and "Secure" in value
        and "Path=/" in value
        for value in cookies
    )
    assert any(
        value.startswith("__Secure-xxx_refresh=")
        and "HttpOnly" in value
        and "Secure" in value
        and "Path=/api/v1/auth" in value
        and "SameSite=strict" in value
        for value in cookies
    )
    assert any(
        value.startswith("__Host-xxx_csrf=")
        and "HttpOnly" not in value
        and "Secure" in value
        and "Path=/" in value
        for value in cookies
    )
