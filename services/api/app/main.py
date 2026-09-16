"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router, compat_router
from app.billing.limits import EntitlementLimitMiddleware
from app.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.database import dispose_engine, init_engine
from app.middleware.correlation import CorrelationIdMiddleware
from app.middleware.csrf import CSRFMiddleware
from app.middleware.hardening import (
    ObservabilityMiddleware,
    RateLimitMiddleware,
    RequestSizeLimitMiddleware,
)
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.observability.metrics import metrics
from app.security.rate_limit import api_rate_limiter, login_abuse_limiter, login_abuse_protector


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    init_engine(settings)
    from app.database.sync_pg import init_sync_engine

    init_sync_engine(settings)
    # Align login abuse settings from config
    login_abuse_protector.max_failures = settings.login_max_failures
    login_abuse_protector.window_seconds = settings.login_window_seconds
    if settings.app_env == "test":
        api_rate_limiter.reset()
        login_abuse_limiter.reset()
        metrics.reset()
    if settings.app_env not in ("production", "test"):
        from uuid import UUID
        from datetime import datetime, timezone
        from app.database.memory import (
            get_memory_store,
            initialize_postgres_persistence,
            OrganizationRecord,
            MembershipRecord,
        )
        from app.domain.enums import OrgRole, MembershipStatus
        from app.billing.service import EntitlementService

        store = get_memory_store()
        default_org_id = UUID("76ec608f-37a4-45fa-bb58-fb81c0710720")
        default_user_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        default_membership_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        now = datetime.now(timezone.utc)

        if settings.persistence_mode == "postgres" and settings.database_url:
            from app.database.postgres_persistence import bootstrap_organization

            bootstrap_organization(
                organization_id=default_org_id,
                user_id=default_user_id,
                name="Acme Corporation",
                slug="acme-corporation",
                plan_code="enterprise",
                membership_id=default_membership_id,
            )
            initialize_postgres_persistence()
        else:
            with store.lock:
                if default_org_id not in store.organizations:
                    store.organizations[default_org_id] = OrganizationRecord(
                        id=default_org_id,
                        name="Acme Corporation",
                        slug="acme-corporation",
                        plan_code="enterprise",
                        status="active",
                        row_version=1,
                        created_at=now,
                        updated_at=now,
                        legal_name="Acme Corporation Inc.",
                        default_timezone="UTC",
                        default_currency="USD",
                    )
                    store.memberships[default_membership_id] = MembershipRecord(
                        id=default_membership_id,
                        organization_id=default_org_id,
                        user_id=default_user_id,
                        role=OrgRole.OWNER,
                        status=MembershipStatus.ACTIVE,
                        created_at=now,
                        updated_at=now,
                    )
        try:
            from app.database.memory import seed_plan_entitlements
            from app.database.seed_company import seed_sample_company

            seed_plan_entitlements(store)
            EntitlementService().ensure_subscription(default_org_id, plan_code="enterprise")
            seed_sample_company(
                store,
                organization_id=default_org_id,
                user_id=default_user_id,
                include_process=True,
            )
        except Exception:
            pass

    logger = get_logger()
    logger.info(
        "api_starting",
        app_env=settings.app_env,
        workflow_mode=settings.workflow_mode,
        persistence_mode=settings.persistence_mode,
    )
    yield
    from app.database.sync_pg import dispose_sync_engine

    dispose_sync_engine()
    await dispose_engine()
    logger.info("api_stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    docs_enabled = settings.app_env != "production"
    application = FastAPI(
        title="Intelligent BPM API",
        version=settings.api_version,
        description=(
            "Multi-tenant intelligent business process management API. "
            "Organization context is taken from X-Organization-Id and membership; "
            "client-provided organization_id values are ignored unless they match."
        ),
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    # Middleware order: in Starlette, last added wraps outermost.
    application.add_middleware(SecurityHeadersMiddleware)
    if settings.enable_csrf:
        application.add_middleware(CSRFMiddleware)
    application.add_middleware(RequestSizeLimitMiddleware)
    if settings.enable_rate_limit:
        application.add_middleware(RateLimitMiddleware)
    application.add_middleware(ObservabilityMiddleware)
    application.add_middleware(CorrelationIdMiddleware)
    application.add_middleware(EntitlementLimitMiddleware)
    # CORSMiddleware added last so it is the outermost middleware on requests and responses
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Organization-Id",
            "X-Correlation-Id",
            "X-CSRF-Token",
            "Idempotency-Key",
            "traceparent",
            "Accept",
        ],
        expose_headers=[
            "X-Correlation-Id",
            "X-Trace-Id",
            "traceparent",
            "Retry-After",
        ],
        max_age=600,
    )
    register_exception_handlers(application)
    application.include_router(api_router)
    application.include_router(compat_router)
    return application


app = create_app()
