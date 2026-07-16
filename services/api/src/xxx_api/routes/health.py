"""Liveness and readiness endpoints."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    """Stable health response contract."""

    status: Literal["ok"] = "ok"


@router.get("/health/live", response_model=HealthResponse, include_in_schema=False)
async def liveness() -> HealthResponse:
    """Confirm that the API process can serve requests."""
    return HealthResponse()


@router.get("/health/ready", response_model=HealthResponse, include_in_schema=False)
async def readiness() -> HealthResponse:
    """Confirm readiness; dependency checks will be added with persistence."""
    return HealthResponse()
