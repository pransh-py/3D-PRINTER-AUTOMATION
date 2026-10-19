"""Owner-only delivery diagnostics and MFA-protected dead-letter retries."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from xxx_api.config import Settings
from xxx_api.dependencies import (
    DatabaseSession,
    OwnerPrincipal,
    RecentMfaOwnerPrincipal,
    get_runtime_settings,
    require_session_csrf,
    require_trusted_origin,
)
from xxx_api.models.notifications import Notification
from xxx_api.routes.commerce import enforce_workflow_limit, no_store
from xxx_api.schemas.commerce import WorkflowSchema
from xxx_api.services.commerce import utc
from xxx_api.services.notifications import retry_notification

router = APIRouter(
    tags=["notifications"], dependencies=[Depends(no_store), Depends(enforce_workflow_limit)]
)


@router.get("/owner/notifications")
async def list_notices(
    _owner: OwnerPrincipal,
    session: DatabaseSession,
    settings: Annotated[Settings, Depends(get_runtime_settings)],
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, object]:
    rows = await session.scalars(
        select(Notification).order_by(Notification.created_at.desc()).limit(limit)
    )
    return {
        "enabled": settings.workflow_notifications_enabled,
        "items": [
            {
                "id": str(row.id),
                "templateCode": row.template_code,
                "status": row.status,
                "attemptCount": row.attempt_count,
                "lastErrorCode": row.last_error_code,
                "createdAt": utc(row.created_at).isoformat(),
                "availableAt": utc(row.available_at).isoformat(),
                "sentAt": utc(row.sent_at).isoformat() if row.sent_at else None,
            }
            for row in rows
        ],
    }


@router.post(
    "/owner/notifications/{notification_id}/retry",
    dependencies=[Depends(require_trusted_origin), Depends(require_session_csrf)],
)
async def retry_notice(
    notification_id: UUID,
    _body: WorkflowSchema,
    owner: RecentMfaOwnerPrincipal,
    session: DatabaseSession,
) -> dict[str, str]:
    await retry_notification(session, owner.user, notification_id)
    return {"status": "pending"}
