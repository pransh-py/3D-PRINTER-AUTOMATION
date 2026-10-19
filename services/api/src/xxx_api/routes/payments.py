"""Buyer Checkout, recent-MFA owner reconciliation and raw signed gateway ingress."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import select

from xxx_api.config import Settings
from xxx_api.dependencies import (
    CurrentPrincipal,
    DatabaseSession,
    OwnerPrincipal,
    RecentMfaOwnerPrincipal,
    get_rate_limiter,
    get_runtime_settings,
    require_session_csrf,
    require_trusted_origin,
)
from xxx_api.domain.roles import Role
from xxx_api.models.commerce import Order, PaymentIntent
from xxx_api.rate_limit import (
    RateLimiter,
    RateLimitExceededError,
    RateLimitRule,
    RateLimitUnavailableError,
)
from xxx_api.razorpay import RazorpayGateway
from xxx_api.routes.commerce import enforce_workflow_limit, no_store
from xxx_api.schemas.commerce import OrderOutput, WorkflowSchema
from xxx_api.services.commerce import WorkflowConflictError, get_order, utc
from xxx_api.services.payments import (
    checkout_return,
    create_checkout,
    ingest_webhook,
    intent_for,
    reconcile_intent,
)


def get_gateway(request: Request) -> RazorpayGateway:
    return request.app.state.payment_gateway  # type: ignore[no-any-return]


Runtime = Annotated[Settings, Depends(get_runtime_settings)]
Gateway = Annotated[RazorpayGateway, Depends(get_gateway)]


class CheckoutReturnInput(WorkflowSchema):
    payment_id: str = Field(pattern=r"^pay_[A-Za-z0-9]+$", max_length=100)
    provider_order_id: str = Field(pattern=r"^order_[A-Za-z0-9]+$", max_length=100)
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")


router = APIRouter(tags=["payments"], dependencies=[Depends(no_store)])
protected = APIRouter(dependencies=[Depends(enforce_workflow_limit)])
write_guards = [Depends(require_trusted_origin), Depends(require_session_csrf)]


@protected.post("/orders/{order_id}/checkout", dependencies=write_guards)
async def checkout(
    order_id: UUID,
    _body: WorkflowSchema,
    principal: CurrentPrincipal,
    session: DatabaseSession,
    settings: Runtime,
    gateway: Gateway,
) -> dict[str, object]:
    intent = await create_checkout(
        session, buyer=principal.user, order_id=order_id, settings=settings, gateway=gateway
    )
    return {
        "intentId": str(intent.id),
        "keyId": settings.razorpay_key_id,
        "displayName": settings.razorpay_checkout_name,
        "providerOrderId": intent.provider_order_id,
        "amountPaise": intent.amount_paise,
        "currency": intent.currency,
        "testMode": settings.razorpay_mode == "test",
    }


@protected.post("/orders/{order_id}/checkout-return", dependencies=write_guards)
async def returned(
    order_id: UUID,
    body: CheckoutReturnInput,
    principal: CurrentPrincipal,
    session: DatabaseSession,
    settings: Runtime,
) -> dict[str, object]:
    order = await checkout_return(
        session,
        buyer=principal.user,
        order_id=order_id,
        payment_id=body.payment_id,
        provider_order_id=body.provider_order_id,
        signature=body.signature,
        settings=settings,
    )
    return OrderOutput.model_validate(order).model_dump(mode="json", by_alias=True)


@protected.post("/orders/{order_id}/reconcile", dependencies=write_guards)
async def buyer_reconcile(
    order_id: UUID,
    _body: WorkflowSchema,
    principal: CurrentPrincipal,
    session: DatabaseSession,
    settings: Runtime,
    gateway: Gateway,
) -> dict[str, object]:
    if principal.user.role is not Role.BUYER:
        raise HTTPException(403, "Use owner reconciliation with recent MFA.")
    order = await get_order(session, user=principal.user, order_id=order_id)
    intent = await intent_for(session, order.id)
    order = await reconcile_intent(
        session, intent=intent, settings=settings, gateway=gateway, actor=principal.user
    )
    return OrderOutput.model_validate(order).model_dump(mode="json", by_alias=True)


@protected.post("/owner/orders/{order_id}/reconcile", dependencies=write_guards)
async def owner_reconcile(
    order_id: UUID,
    _body: WorkflowSchema,
    owner: RecentMfaOwnerPrincipal,
    session: DatabaseSession,
    settings: Runtime,
    gateway: Gateway,
) -> dict[str, object]:
    order = await get_order(session, user=owner.user, order_id=order_id)
    intent = await intent_for(session, order.id)
    order = await reconcile_intent(
        session, intent=intent, settings=settings, gateway=gateway, actor=owner.user
    )
    return OrderOutput.model_validate(order).model_dump(mode="json", by_alias=True)


@protected.get("/owner/payments")
async def owner_payments(
    _owner: OwnerPrincipal,
    session: DatabaseSession,
    settings: Runtime,
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, object]:
    rows = await session.execute(
        select(PaymentIntent, Order)
        .join(Order)
        .order_by(PaymentIntent.created_at.desc())
        .limit(limit)
    )
    return {
        "items": [
            {
                "id": str(intent.id),
                "orderId": str(order.id),
                "publicReference": order.public_reference,
                "status": intent.status,
                "orderStatus": order.status,
                "amountPaise": intent.amount_paise,
                "currency": intent.currency,
                "testMode": settings.environment == "test"
                or bool(intent.provider_key_id and intent.provider_key_id.startswith("rzp_test_")),
                "failureCode": intent.failure_code,
                "providerOrderId": intent.provider_order_id,
                "lastReconciledAt": utc(intent.last_reconciled_at).isoformat()
                if intent.last_reconciled_at
                else None,
            }
            for intent, order in rows
        ]
    }


@router.post("/payments/razorpay/webhook")
async def webhook(
    request: Request,
    session: DatabaseSession,
    settings: Runtime,
    gateway: Gateway,
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> dict[str, str]:
    try:
        await limiter.enforce(
            "razorpay-ingress",
            (
                RateLimitRule(
                    request.client.host if request.client else "unknown",
                    limit=300,
                    window_seconds=60,
                ),
            ),
        )
    except RateLimitExceededError as error:
        raise HTTPException(
            429,
            "Webhook rate limit exceeded",
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from None
    except RateLimitUnavailableError:
        raise HTTPException(503, "Webhook protection unavailable") from None
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 256 * 1024:
            raise HTTPException(413, "Webhook exceeds the safe limit")
        raw.extend(chunk)
    try:
        event = await ingest_webhook(
            session,
            raw=bytes(raw),
            signature=request.headers.get("x-razorpay-signature", ""),
            provider_event_id=request.headers.get("x-razorpay-event-id", ""),
            settings=settings,
            gateway=gateway,
        )
    except WorkflowConflictError as error:
        raise HTTPException(400, str(error)) from None
    return {"status": event.status}


router.include_router(protected)
