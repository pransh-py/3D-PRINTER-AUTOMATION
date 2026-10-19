"""Real cookie/CSRF/MFA HTTP boundaries in a disposable, fictional payment lab."""

import hmac
import json
from uuid import uuid4

import pyotp
from fastapi.testclient import TestClient
from test_payments import signed_payload
from workflow_lab import create_payment_lab

from xxx_api.services.commerce import enqueue_paid_orders

ORIGIN = "http://127.0.0.1:3100"


def test_payment_http_cookie_csrf_price_tampering_owner_gate_and_raw_webhook():
    app = create_payment_lab()
    with TestClient(app, base_url=ORIGIN) as client:
        access = json.loads(app.state.lab_access_file.read_text())
        order_id = access["orderId"]
        checkout_url = f"/api/v1/orders/{order_id}/checkout"
        assert client.post(checkout_url, json={}).status_code == 401
        login = client.post(
            "/api/v1/auth/login",
            headers={"Origin": ORIGIN},
            json={"email": access["buyerEmail"], "password": access["password"]},
        )
        assert login.status_code == 200
        headers = {"Origin": ORIGIN, "X-CSRF-Token": client.cookies.get("xxx_csrf")}
        assert client.get("/api/v1/owner/payments").status_code == 403
        assert client.get("/api/v1/owner/notifications").status_code == 403
        assert client.post(checkout_url, json={}).status_code == 403
        assert (
            client.post(checkout_url, json={"amountPaise": 1}, headers=headers).status_code == 422
        )
        assert (
            client.post(f"/api/v1/orders/{uuid4()}/checkout", json={}, headers=headers).status_code
            == 404
        )
        response = client.post(checkout_url, json={}, headers=headers)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert set(response.json()) == {
            "intentId",
            "keyId",
            "displayName",
            "providerOrderId",
            "amountPaise",
            "currency",
            "testMode",
        }
        assert response.json()["testMode"] is True
        gateway = app.state.payment_gateway
        assert response.json()["amountPaise"] == gateway.order.amount
        signature = hmac.new(
            app.state.settings.razorpay_key_secret.get_secret_value().encode(),
            b"order_Fictional|pay_Fictional",
            "sha256",
        ).hexdigest()
        callback = client.post(
            f"/api/v1/orders/{order_id}/checkout-return",
            headers=headers,
            json={
                "paymentId": "pay_Fictional",
                "providerOrderId": "order_Fictional",
                "signature": signature,
            },
        )
        assert callback.status_code == 200 and callback.json()["status"] == "payment_processing"
        assert client.portal.call(_enqueue, app) == 0
        gateway.capture()
        raw, signed = signed_payload(gateway, app.state.settings)
        webhook = "/api/v1/payments/razorpay/webhook"
        assert client.post(webhook, content=raw).status_code == 400
        provider_headers = {"x-razorpay-signature": signed, "x-razorpay-event-id": "evt_HttpLab"}
        assert client.post(webhook, content=raw + b" ", headers=provider_headers).status_code == 400
        # Gateway ingress is signed server-to-server; it must not require buyer cookies/CSRF.
        client.cookies.clear()
        assert client.post(webhook, content=raw, headers=provider_headers).json() == {
            "status": "processed"
        }
        assert client.post(webhook, content=raw, headers=provider_headers).status_code == 200
        assert client.portal.call(_enqueue, app) == 1
        assert client.portal.call(_enqueue, app) == 0
        assert (
            client.post(
                webhook, content=b"x" * (256 * 1024 + 1), headers=provider_headers
            ).status_code
            == 413
        )
        login = client.post(
            "/api/v1/auth/login",
            headers={"Origin": ORIGIN},
            json={"email": access["ownerEmail"], "password": access["password"]},
        )
        assert login.status_code == 202
        mfa = client.post(
            "/api/v1/auth/login/mfa",
            headers={"Origin": ORIGIN},
            json={
                "challenge": login.json()["challenge"],
                "code": pyotp.TOTP(access["totpSecret"]).now(),
            },
        )
        assert mfa.status_code == 200
        owner_headers = {"Origin": ORIGIN, "X-CSRF-Token": client.cookies.get("xxx_csrf")}
        assert (
            client.post(
                f"/api/v1/orders/{order_id}/reconcile", json={}, headers=owner_headers
            ).status_code
            == 403
        )
        payments = client.get("/api/v1/owner/payments")
        assert payments.status_code == 200 and payments.json()["items"][0]["status"] == "captured"
        assert payments.json()["items"][0]["testMode"] is True
        notices = client.get("/api/v1/owner/notifications")
        assert notices.status_code == 200 and notices.json() == {"enabled": False, "items": []}
        retry_url = f"/api/v1/owner/notifications/{uuid4()}/retry"
        assert client.post(retry_url, json={}).status_code == 403
        assert (
            client.post(
                retry_url, json={"recipient": "attacker@example.com"}, headers=owner_headers
            ).status_code
            == 422
        )
        assert client.post(retry_url, json={}, headers=owner_headers).status_code == 404
        assert (
            client.post(
                f"/api/v1/owner/orders/{order_id}/reconcile", json={}, headers=owner_headers
            ).status_code
            == 200
        )
        assert client.get(f"/api/v1/orders/{order_id}").json()["status"] == "queued"


async def _enqueue(app):
    async with app.state.session_factory() as session:
        return await enqueue_paid_orders(session)
