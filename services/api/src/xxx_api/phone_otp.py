"""Server-only OTPigeon delivery. No retries, redirects, proxy environment or code logging."""

import asyncio
import json
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from xxx_api.config import Settings


class PhoneOtpDeliveryError(Exception):
    def __init__(
        self, reason: Literal["unavailable", "unreachable_number", "failed", "ack_lost"] = "failed"
    ) -> None:
        super().__init__("WhatsApp code delivery failed")
        self.reason = reason


class PhoneOtpSender(Protocol):
    async def send_code(self, phone_e164: str, code: str) -> None: ...


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: object, code: int, msg: str, headers: object, newurl: str
    ) -> None:
        return None


class OtpigeonWhatsAppSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _send(self, phone_e164: str, code: str) -> None:
        key = self.settings.whatsapp_otp_sender_api_key
        if not self.settings.whatsapp_otp_enabled or key is None:
            raise PhoneOtpDeliveryError("unavailable")
        request = Request(
            str(self.settings.whatsapp_otp_sender_url).rstrip("/") + "/send-otp",
            data=json.dumps({"phone": phone_e164, "otp": code}).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-SENDER-API-KEY": key.get_secret_value(),
            },
        )
        try:
            with build_opener(ProxyHandler({}), NoRedirect()).open(
                request, timeout=self.settings.whatsapp_otp_timeout_seconds
            ) as response:
                raw = response.read(4097)
                if len(raw) > 4096 or response.status != 200:
                    raise PhoneOtpDeliveryError("failed")
                result = json.loads(raw)
                if not isinstance(result, dict) or result.get("sent") is not True:
                    raise PhoneOtpDeliveryError("failed")
        except HTTPError as error:
            if error.code == 404:
                try:
                    result = json.loads(error.read(4096))
                    if isinstance(result, dict) and result.get("error") == "number_not_registered":
                        raise PhoneOtpDeliveryError("unreachable_number") from None
                except (ValueError, OSError):
                    pass
            raise PhoneOtpDeliveryError("unavailable" if error.code == 503 else "failed") from None
        except (URLError, TimeoutError, OSError):
            raise PhoneOtpDeliveryError("unavailable") from None
        except ValueError:
            raise PhoneOtpDeliveryError("failed") from None

    async def send_code(self, phone_e164: str, code: str) -> None:
        await asyncio.to_thread(self._send, phone_e164, code)
