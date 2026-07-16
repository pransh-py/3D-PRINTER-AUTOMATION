"""Liveness and readiness endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from xxx_api.database import get_session
from xxx_api.storage import ObjectStorageError

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    """Stable health response contract."""

    status: Literal["ok"] = "ok"


@router.get("/health/live", response_model=HealthResponse, include_in_schema=False)
async def liveness() -> HealthResponse:
    """Confirm that the API process can serve requests."""
    return HealthResponse()


@router.get("/health/ready", response_model=HealthResponse, include_in_schema=False)
async def readiness(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HealthResponse:
    """Confirm that database, Redis, and private storage can serve traffic."""
    try:
        await session.execute(text("SELECT 1"))
        await request.app.state.redis.ping()
        await request.app.state.object_storage.check_ready()
    except (SQLAlchemyError, RedisError, ObjectStorageError, OSError, TimeoutError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready",
        ) from error
    return HealthResponse()
