"""Append-only audit-event construction shared by transactional services."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from xxx_api.domain.auth import AuditEventType
from xxx_api.models.identity import AuditEvent


def append_audit_event(
    session: AsyncSession,
    event_type: AuditEventType,
    *,
    occurred_at: datetime,
    actor_user_id: UUID | None = None,
    target_user_id: UUID | None = None,
    session_id: UUID | None = None,
    request_id: str | None = None,
    details: dict[str, object] | None = None,
) -> None:
    """Stage one reviewed non-secret event in the caller's transaction."""
    session.add(
        AuditEvent(
            event_type=event_type,
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            session_id=session_id,
            request_id=request_id,
            occurred_at=occurred_at,
            details=details or {},
        )
    )
