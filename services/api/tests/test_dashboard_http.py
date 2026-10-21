"""Role-isolated dashboard summaries through real cookie sessions in disposable state."""

from asyncio import run
from datetime import UTC, datetime, timedelta
from json import loads
from uuid import uuid4

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from test_commerce import seed_commerce
from workflow_lab import create_lab

from xxx_api.domain.auth import UserStatus
from xxx_api.domain.quotes import QuoteRequestStatus
from xxx_api.domain.roles import Role
from xxx_api.models.identity import RefreshSession, User
from xxx_api.models.quotes import QuoteRequest
from xxx_api.security.passwords import hash_password
from xxx_api.services.commerce import issue_quote

ORIGIN = "http://127.0.0.1:3100"


class LabAccess(dict):
    def __repr__(self):
        return "<fictional lab credentials redacted>"


@pytest.fixture
def lab():
    app = create_lab()
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, app, LabAccess(loads(app.state.lab_access_file.read_text()))


def login(client, access, *, owner=False, email=None):
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN},
        json={
            "email": email or access["ownerEmail" if owner else "buyerEmail"],
            "password": access["password"],
        },
    )
    if owner:
        assert response.status_code == 202
        response = client.post(
            "/api/v1/auth/login/mfa",
            headers={"Origin": ORIGIN},
            json={
                "challenge": response.json()["challenge"],
                "code": pyotp.TOTP(access["totpSecret"]).now(),
            },
        )
    assert response.status_code == 200
    return response.json()


def test_dashboard_role_gates_private_contract_and_existing_resource_scoping(lab):
    client, app, access = lab
    for path in ("/owner/dashboard", "/buyer/dashboard"):
        response = client.get(f"/api/v1{path}")
        assert response.status_code == 401
        assert response.headers["cache-control"] == "no-store"
        assert client.post(f"/api/v1{path}", json={}).status_code == 405

    login(client, access, owner=True)
    assert client.get("/api/v1/buyer/dashboard").status_code == 403
    response = client.get("/api/v1/owner/dashboard")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert set(data) == {
        "generatedAt",
        "quoteRequests",
        "openQuotations",
        "orders",
        "printJobs",
        "payments",
        "fulfillments",
        "notifications",
        "setup",
    }
    assert data["orders"] == {"queued": 1}
    assert data["printJobs"] == {"queued": 1}
    assert data["payments"] == {"captured": 1}
    assert data["fulfillments"] == {"pending": 1}
    assert data["openQuotations"] == 0
    assert data["setup"] == {
        "ownerMfaEnabled": True,
        "pricingPolicyActive": True,
        "onlinePaymentsEnabled": False,
        "paymentsTestMode": False,
    }
    assert data["notifications"] == {"enabled": False, "counts": {}}
    for forbidden in ("@", "email", "address", "Paise", access["orderId"]):
        assert forbidden not in response.text
    assert datetime.fromisoformat(data["generatedAt"]).utcoffset() == timedelta(0)
    assert len(client.get("/api/v1/orders").json()["items"]) == 1

    client.cookies.clear()
    login(client, access)
    assert client.get("/api/v1/owner/dashboard").status_code == 403
    buyer_data = client.get("/api/v1/buyer/dashboard").json()
    assert set(buyer_data) == {
        "generatedAt",
        "quoteRequests",
        "openQuotations",
        "orders",
        "payments",
    }
    assert buyer_data["orders"] == {"queued": 1}
    assert buyer_data["payments"] == {"onlineEnabled": False, "testMode": False}

    async def add_second_buyer():
        async with app.state.session_factory() as session:
            now = datetime.now(UTC)
            session.add(
                User(
                    id=uuid4(),
                    email="second@lab.example",
                    display_name="Second lab buyer",
                    password_hash=hash_password(access["password"]),
                    role=Role.BUYER,
                    status=UserStatus.ACTIVE,
                    email_verified_at=now,
                    password_changed_at=now,
                )
            )
            await session.commit()

    client.portal.call(add_second_buyer)
    client.cookies.clear()
    login(client, access, email="second@lab.example")
    second = client.get("/api/v1/buyer/dashboard").json()
    assert second["orders"] == second["quoteRequests"] == {}
    assert second["openQuotations"] == 0
    for path in ("orders", "quotations", "quote-requests"):
        assert client.get(f"/api/v1/{path}").json()["items"] == []
    assert client.get(f"/api/v1/orders/{access['orderId']}").status_code == 404


def test_dashboard_counts_are_not_limited_and_revocation_fails_closed(lab):
    client, app, access = lab
    user = login(client, access)

    async def insert_requests():
        async with app.state.session_factory() as session:
            buyer = await session.scalar(select(User).where(User.email == access["buyerEmail"]))
            session.add_all(
                [
                    QuoteRequest(
                        buyer_id=buyer.id, client_token=uuid4(), status=QuoteRequestStatus.DRAFT
                    )
                    for _ in range(125)
                ]
            )
            await session.commit()

    client.portal.call(insert_requests)
    data = client.get("/api/v1/buyer/dashboard").json()
    assert data["quoteRequests"]["draft"] == 125
    assert sum(data["quoteRequests"].values()) == 126

    async def revoke():
        async with app.state.session_factory() as session:
            buyer = await session.scalar(select(User).where(User.email == user["email"]))
            await session.execute(
                update(RefreshSession)
                .where(RefreshSession.user_id == buyer.id)
                .values(revoked_at=datetime.now(UTC))
            )
            await session.commit()

    client.portal.call(revoke)
    assert client.get("/api/v1/buyer/dashboard").status_code == 401


def test_open_quotation_count_excludes_expiry_and_disabled_test_mode():
    async def scenario():
        from xxx_api.config import Settings
        from xxx_api.services.dashboard import buyer_dashboard

        engine, sessions, owner, buyer, request, estimate = await seed_commerce()
        try:
            now = datetime.now(UTC)
            async with sessions() as session:
                await issue_quote(
                    session,
                    owner=owner,
                    request_id=request.id,
                    estimate_id=estimate.id,
                    expected_version=request.version,
                    expires_at=now + timedelta(hours=1),
                )
                settings = Settings(
                    environment="test", razorpay_enabled=False, razorpay_mode="test"
                )
                current = await buyer_dashboard(session, buyer, settings, now=now)
                expired = await buyer_dashboard(
                    session, buyer, settings, now=now + timedelta(hours=2)
                )
                assert current["openQuotations"] == 1
                assert expired["openQuotations"] == 0
                assert current["payments"] == {"onlineEnabled": False, "testMode": False}
        finally:
            await engine.dispose()

    run(scenario())


def test_enabled_test_checkout_is_explicit_in_both_dashboards():
    app = create_lab(payments=True)
    with TestClient(app, base_url=ORIGIN) as client:
        access = LabAccess(loads(app.state.lab_access_file.read_text()))
        login(client, access)
        assert client.get("/api/v1/buyer/dashboard").json()["payments"] == {
            "onlineEnabled": True,
            "testMode": True,
        }
        client.cookies.clear()
        login(client, access, owner=True)
        setup = client.get("/api/v1/owner/dashboard").json()["setup"]
        assert setup["onlinePaymentsEnabled"] is True
        assert setup["paymentsTestMode"] is True
