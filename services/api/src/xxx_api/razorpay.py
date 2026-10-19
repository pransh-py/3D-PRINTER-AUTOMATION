"""Bounded server-only Razorpay transport and minimal, non-sensitive DTOs."""

import asyncio
import base64
import json
import re
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError

from xxx_api.config import Settings


class GatewayUnavailableError(Exception):
    """An unavailable or invalid provider response; never includes provider payloads."""


class ProviderOrder(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(pattern=r"^order_[A-Za-z0-9]+$", max_length=100)
    entity: Literal["order"]
    amount: StrictInt = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    receipt: str = Field(max_length=40)
    status: Literal["created", "attempted", "paid"]
    amount_paid: StrictInt = Field(ge=0)
    amount_due: StrictInt = Field(ge=0)


class ProviderPayment(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(pattern=r"^pay_[A-Za-z0-9]+$", max_length=100)
    entity: Literal["payment"]
    order_id: str = Field(pattern=r"^order_[A-Za-z0-9]+$", max_length=100)
    amount: StrictInt = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    status: Literal["created", "authorized", "captured", "failed", "refunded"]
    captured: StrictBool
    amount_refunded: StrictInt = Field(ge=0)


class RazorpayGateway(Protocol):
    async def create_order(self, *, amount: int, receipt: str) -> ProviderOrder: ...

    async def find_orders(self, *, receipt: str) -> list[ProviderOrder]: ...

    async def fetch_order(self, order_id: str) -> ProviderOrder: ...

    async def fetch_payment(self, payment_id: str) -> ProviderPayment: ...

    async def order_payments(self, order_id: str) -> list[ProviderPayment]: ...


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: object, code: int, msg: str, headers: object, newurl: str
    ) -> None:
        return None


class HttpRazorpayGateway:
    """Fixed HTTPS destination, no redirects/proxy environment or automatic write retries."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _request(self, path: str, body: dict[str, object] | None = None) -> object:
        secret = self.settings.razorpay_key_secret
        if not self.settings.razorpay_enabled or secret is None:
            raise GatewayUnavailableError("Online payment is not configured.")
        credentials = f"{self.settings.razorpay_key_id}:{secret.get_secret_value()}".encode()
        authorization = base64.b64encode(credentials).decode("ascii")
        request = Request(
            f"https://api.razorpay.com/v1/{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Basic {authorization}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST" if body is not None else "GET",
        )
        try:
            with build_opener(ProxyHandler({}), NoRedirect()).open(
                request, timeout=self.settings.razorpay_timeout_seconds
            ) as response:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise GatewayUnavailableError("Provider response exceeded the safe limit.")
                return json.loads(raw)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            # Do not propagate response bodies, URLs or credential-bearing Request objects.
            raise GatewayUnavailableError("Payment provider is temporarily unavailable.") from None

    async def create_order(self, *, amount: int, receipt: str) -> ProviderOrder:
        value = await asyncio.to_thread(
            self._request,
            "orders",
            {"amount": amount, "currency": "INR", "receipt": receipt, "partial_payment": False},
        )
        return self._order(value)

    async def find_orders(self, *, receipt: str) -> list[ProviderOrder]:
        value = await asyncio.to_thread(
            self._request, f"orders?{urlencode({'receipt': receipt, 'count': 100})}"
        )
        items = self._items(value)
        if len(items) >= 100:
            raise GatewayUnavailableError("Receipt search requires owner investigation.")
        return [self._order(item) for item in items]

    async def fetch_order(self, order_id: str) -> ProviderOrder:
        self._identifier(order_id, "order")
        return self._order(await asyncio.to_thread(self._request, f"orders/{order_id}"))

    async def fetch_payment(self, payment_id: str) -> ProviderPayment:
        self._identifier(payment_id, "pay")
        return self._payment(await asyncio.to_thread(self._request, f"payments/{payment_id}"))

    async def order_payments(self, order_id: str) -> list[ProviderPayment]:
        self._identifier(order_id, "order")
        value = await asyncio.to_thread(self._request, f"orders/{order_id}/payments")
        return [self._payment(item) for item in self._items(value)]

    @staticmethod
    def _identifier(value: str, prefix: str) -> None:
        if len(value) > 100 or re.fullmatch(rf"{prefix}_[A-Za-z0-9]+", value) is None:
            raise GatewayUnavailableError("Invalid provider identifier.")

    @staticmethod
    def _items(value: object) -> list[object]:
        if (
            not isinstance(value, dict)
            or value.get("entity") != "collection"
            or not isinstance(value.get("items"), list)
            or type(value.get("count")) is not int
            or value["count"] != len(value["items"])
            or len(value["items"]) > 100
        ):
            raise GatewayUnavailableError("Invalid provider collection.")
        return list(value["items"])

    @staticmethod
    def _order(value: object) -> ProviderOrder:
        try:
            return ProviderOrder.model_validate(value)
        except ValidationError:
            raise GatewayUnavailableError("Invalid provider order response.") from None

    @staticmethod
    def _payment(value: object) -> ProviderPayment:
        try:
            return ProviderPayment.model_validate(value)
        except ValidationError:
            raise GatewayUnavailableError("Invalid provider payment response.") from None
