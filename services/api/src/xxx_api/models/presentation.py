"""Free presentation admissions, isolated from payment and commercial orders."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from xxx_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PresentationEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "presentation_entries"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_presentation_version"),
        CheckConstraint(
            "status IN ('waiting','approved','claimed','starting','printing','completed',"
            "'needs_attention','rejected','cancelled','stopped','refused')",
            name="ck_presentation_status",
        ),
        Index("ix_presentation_fifo", "status", "approved_at", "id"),
    )
    quote_request_id: Mapped[UUID] = mapped_column(ForeignKey("quote_requests.id"), unique=True)
    buyer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    estimate_id: Mapped[UUID] = mapped_column(ForeignKey("quote_estimates.id"))
    status: Mapped[str] = mapped_column(String(24), default="waiting")
    version: Mapped[int] = mapped_column(Integer, default=1)
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authorization_id: Mapped[UUID | None] = mapped_column(unique=True)
    bridge_id: Mapped[UUID | None] = mapped_column(ForeignKey("bridge_installations.id"))
    printer_filename: Mapped[str | None] = mapped_column(String(96))
    dispatch_sha256: Mapped[str | None] = mapped_column(String(64))
    progress_bps: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str | None] = mapped_column(Text)
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class PresentationStation(Base):
    __tablename__ = "presentation_station"
    __table_args__ = (CheckConstraint("id = 1 AND version > 0", name="ck_presentation_singleton"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(24), default="offline")
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_entry_id: Mapped[UUID | None] = mapped_column(ForeignKey("presentation_entries.id"))
    clear_entry_id: Mapped[UUID | None] = mapped_column(ForeignKey("presentation_entries.id"))
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
