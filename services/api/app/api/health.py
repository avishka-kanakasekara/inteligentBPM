"""Health, readiness, metrics, and alerts routes."""

from __future__ import annotations

from typing import Any

from bpm_contracts import HealthResponse, ReadinessResponse
from fastapi import APIRouter, Response, status

from app import __version__
from app.core.settings import Settings, get_settings
from app.observability.alerts import alerts_as_dicts
from app.observability.errors import error_tracker
from app.observability.metrics import metrics
from app.services.readiness import build_readiness, check_migrations

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(service=settings.app_name, version=__version__)


@router.get("/readyz", response_model=ReadinessResponse)
async def readyz(response: Response) -> ReadinessResponse:
    settings: Settings = get_settings()
    result = await build_readiness(settings)
    if not result.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result


@router.get("/healthz/deps")
async def health_dependencies() -> dict[str, Any]:
    """Explicit dependency probe for operators."""
    settings = get_settings()
    from app.services.readiness import (
        check_database,
        check_redis,
        check_secrets,
        check_supabase_auth,
    )

    checks = [
        (await check_database(settings)).model_dump(),
        (await check_redis(settings)).model_dump(),
        (await check_supabase_auth(settings)).model_dump(),
        check_migrations(settings).model_dump(),
        check_secrets(settings).model_dump(),
    ]
    return {"service": settings.app_name, "checks": checks}


@router.get("/metrics")
async def get_metrics() -> dict[str, Any]:
    return metrics.snapshot()


@router.get("/alerts")
async def get_alerts() -> dict[str, Any]:
    return {"alerts": alerts_as_dicts()}


@router.get("/errors/recent")
async def recent_errors() -> dict[str, Any]:
    return {"errors": error_tracker.recent(limit=50)}
