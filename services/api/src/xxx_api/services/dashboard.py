"""Read-only counts from persisted business state, never from truncated UI lists."""

from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from xxx_api.config import Settings
from xxx_api.models.commerce import Fulfillment, Order, PaymentIntent, PrintJob, Quote
from xxx_api.models.identity import User
from xxx_api.models.notifications import Notification
from xxx_api.models.pricing import PricingPolicy
from xxx_api.models.quotes import QuoteRequest
from xxx_api.services.commerce import utc
from xxx_api.services.owner_security import owner_mfa_enabled


async def _states[State: str](
    session: AsyncSession, statement: Select[tuple[State, int]]
) -> dict[str, int]:
    return {str(state): count for state, count in await session.execute(statement)}


async def buyer_dashboard(
    session: AsyncSession, buyer: User, settings: Settings, *, now: datetime | None = None
) -> dict[str, object]:
    generated_at = utc(now)
    requests = await _states(
        session,
        select(QuoteRequest.status, func.count())
        .where(QuoteRequest.buyer_id == buyer.id)
        .group_by(QuoteRequest.status),
    )
    orders = await _states(
        session,
        select(Order.status, func.count()).where(Order.buyer_id == buyer.id).group_by(Order.status),
    )
    open_quotes = await session.scalar(
        select(func.count())
        .select_from(Quote)
        .join(QuoteRequest)
        .where(
            QuoteRequest.buyer_id == buyer.id,
            Quote.status == "issued",
            Quote.expires_at > generated_at,
        )
    )
    return {
        "generatedAt": generated_at.isoformat(),
        "quoteRequests": requests,
        "openQuotations": int(open_quotes or 0),
        "orders": orders,
        "payments": {
            "onlineEnabled": settings.razorpay_enabled,
            "testMode": settings.razorpay_enabled and settings.razorpay_mode == "test",
        },
    }


async def owner_dashboard(
    session: AsyncSession, owner: User, settings: Settings
) -> dict[str, object]:
    mfa_enabled = await owner_mfa_enabled(session, owner)
    generated_at = utc()
    requests = await _states(
        session, select(QuoteRequest.status, func.count()).group_by(QuoteRequest.status)
    )
    orders = await _states(session, select(Order.status, func.count()).group_by(Order.status))
    jobs = await _states(session, select(PrintJob.status, func.count()).group_by(PrintJob.status))
    payments = await _states(
        session, select(PaymentIntent.status, func.count()).group_by(PaymentIntent.status)
    )
    fulfillments = await _states(
        session, select(Fulfillment.status, func.count()).group_by(Fulfillment.status)
    )
    notices = await _states(
        session, select(Notification.status, func.count()).group_by(Notification.status)
    )
    open_quotes = await session.scalar(
        select(func.count())
        .select_from(Quote)
        .where(Quote.status == "issued", Quote.expires_at > generated_at)
    )
    pricing_active = bool(
        await session.scalar(
            select(select(PricingPolicy.id).where(PricingPolicy.status == "active").exists())
        )
    )
    return {
        "generatedAt": generated_at.isoformat(),
        "quoteRequests": requests,
        "openQuotations": int(open_quotes or 0),
        "orders": orders,
        "printJobs": jobs,
        "payments": payments,
        "fulfillments": fulfillments,
        "notifications": {"enabled": settings.workflow_notifications_enabled, "counts": notices},
        "setup": {
            "ownerMfaEnabled": mfa_enabled,
            "pricingPolicyActive": pricing_active,
            "onlinePaymentsEnabled": settings.razorpay_enabled,
            "paymentsTestMode": settings.razorpay_enabled and settings.razorpay_mode == "test",
        },
    }
