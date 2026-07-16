"""Provider-neutral transactional email content tests."""

from asyncio import run
from email.message import EmailMessage

from xxx_api.config import Settings
from xxx_api.email import SmtpEmailSender


class CapturingSmtpEmailSender(SmtpEmailSender):
    """Capture the composed message without opening a network connection."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.messages: list[EmailMessage] = []

    async def _deliver(self, message: EmailMessage) -> None:
        self.messages.append(message)


def test_verification_email_uses_public_web_url_and_never_logs() -> None:
    sender = CapturingSmtpEmailSender(
        Settings(environment="test", public_web_url="http://localhost:3000")
    )

    run(sender.send_verification("buyer@example.com", "raw-verification-token"))

    assert len(sender.messages) == 1
    message = sender.messages[0]
    assert message["To"] == "buyer@example.com"
    assert "http://localhost:3000/verify-email#token=raw-verification-token" in str(
        message.get_content()
    )


def test_password_reset_email_targets_reset_screen() -> None:
    sender = CapturingSmtpEmailSender(Settings(environment="test"))

    run(sender.send_password_reset("buyer@example.com", "raw-reset-token"))

    assert "http://localhost:3000/reset-password#token=raw-reset-token" in str(
        sender.messages[0].get_content()
    )
