"""Distinct role-gated dashboard summaries without private records or machine control."""

from typing import Annotated

from fastapi import APIRouter, Depends

from xxx_api.config import Settings
from xxx_api.dependencies import (
    BuyerPrincipal,
    DatabaseSession,
    OwnerPrincipal,
    get_runtime_settings,
)
from xxx_api.routes.commerce import enforce_workflow_limit, no_store
from xxx_api.services.dashboard import buyer_dashboard, owner_dashboard

router = APIRouter(
    tags=["dashboards"], dependencies=[Depends(no_store), Depends(enforce_workflow_limit)]
)
RuntimeSettings = Annotated[Settings, Depends(get_runtime_settings)]


@router.get("/buyer/dashboard")
async def buyer_summary(
    buyer: BuyerPrincipal, session: DatabaseSession, settings: RuntimeSettings
) -> dict[str, object]:
    return await buyer_dashboard(session, buyer.user, settings)


@router.get("/owner/dashboard")
async def owner_summary(
    owner: OwnerPrincipal, session: DatabaseSession, settings: RuntimeSettings
) -> dict[str, object]:
    return await owner_dashboard(session, owner.user, settings)
