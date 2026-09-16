"""API router aggregation.

Canonical prefix: /v1 (as specified for this backend foundation phase).
Health endpoints remain available under /v1 and /api/v1 for compatibility.
"""

from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.v1 import (
    allocation,
    approvals,
    auth,
    billing,
    discovery,
    documents,
    execution,
    imports,
    org_data,
    organizations,
    process_runs,
    processes,
    risk,
    workspace,
)

api_router = APIRouter(prefix="/v1")
api_router.include_router(health_router)
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(org_data.router)
api_router.include_router(imports.router)
api_router.include_router(documents.router)
api_router.include_router(processes.router)
api_router.include_router(discovery.router)
api_router.include_router(allocation.router)
api_router.include_router(risk.router)
api_router.include_router(execution.router)
api_router.include_router(approvals.router)
api_router.include_router(process_runs.router)
api_router.include_router(billing.router)
api_router.include_router(workspace.router)

# Compatibility alias for earlier foundation health checks
compat_router = APIRouter(prefix="/api/v1")
compat_router.include_router(health_router)
