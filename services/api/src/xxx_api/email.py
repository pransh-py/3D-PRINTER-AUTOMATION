"""Provider-neutral transactional email boundary and SMTP adapter."""

from email.message import EmailMessage
from smtplib import SMTP, SMTP_SSL
from ssl import create_default_context
from typing import Protocol

from anyio import to_thread

from xxx_api.config import Settings


class EmailDeliveryError(Exception):
    """The configured delivery provider did not accept a message."""


class EmailSender(Protocol):
    """Transactional messages required by the identity flow."""

    async def send_verification(self, recipient: str, raw_token: str) -> None:
        """Send one email-verification link."""

    async def send_password_reset(self, recipient: str, raw_token: str) -> None:
        """Send one password-reset link."""


class SmtpEmailSender:
    """Send transactional mail through any standards-compliant SMTP provider."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send_verification(self, recipient: str, raw_token: str) -> None:
        link = f"{str(self._settings.public_web_url).rstrip('/')}/verify-email#token={raw_token}"
        message = self._message(
            recipient=recipient,
            subject="Verify your xxx account",
            body=(
                "Verify your email address to activate your xxx account.\n\n"
                f"{link}\n\n"
                "If you did not request this account, you can ignore this email."
            ),
        )
        await self._deliver(message)

    async def send_password_reset(self, recipient: str, raw_token: str) -> None:
        link = f"{str(self._settings.public_web_url).rstrip('/')}/reset-password#token={raw_token}"
        message = self._message(
            recipient=recipient,
            subject="Reset your xxx password",
            body=(
                "Use this link to choose a new password for your xxx account.\n\n"
                f"{link}\n\n"
                "If you did not request a reset, you can ignore this email."
            ),
        )
        await self._deliver(message)

    def _message(self, *, recipient: str, subject: str, body: str) -> EmailMessage:
        message = EmailMessage()
        message["From"] = (
            f"{self._settings.email_sender_name} <{self._settings.email_sender_address}>"
        )
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        return message

    async def _deliver(self, message: EmailMessage) -> None:
        try:
            await to_thread.run_sync(self._deliver_sync, message)
        except Exception as error:
            raise EmailDeliveryError("transactional email delivery failed") from error

    def _deliver_sync(self, message: EmailMessage) -> None:
        settings = self._settings
        smtp_type = SMTP_SSL if settings.smtp_use_tls else SMTP
        with smtp_type(
            host=settings.smtp_host,
            port=settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
        ) as smtp:
            if settings.smtp_starttls:
                smtp.starttls(context=create_default_context())
            if settings.smtp_username and settings.smtp_password:
                smtp.login(
                    settings.smtp_username,
                    settings.smtp_password.get_secret_value(),
                )
            smtp.send_message(message)
