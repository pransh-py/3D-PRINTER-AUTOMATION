"""Private delivery records for transactional workflow notices."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from xxx_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint(
            "outbox_event_id",
            "recipient_user_id",
            "template_code",
            name="uq_notifications_event_recipient_template",
        ),
        CheckConstraint("channel = 'email'", name="ck_notifications_channel"),
        CheckConstraint(
            "status IN ('pending','sent','failed','dead_lettered')", name="ck_notifications_status"
        ),
        CheckConstraint("attempt_count >= 0", name="ck_notifications_attempt_count"),
        CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_notifications_lease_pair",
        ),
        Index("ix_notifications_delivery", "status", "available_at"),
    )

    outbox_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("outbox_events.id", ondelete="RESTRICT"), nullable=False
    )
    recipient_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    channel: Mapped[str] = mapped_column(String(16), default="email", server_default="email")
    template_code: Mapped[str] = mapped_column(String(64), nullable=False)
    template_version: Mapped[str] = mapped_column(String(16), default="1", server_default="1")
    destination_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    lease_token: Mapped[UUID | None]
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
