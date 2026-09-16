"""Application configuration (Pydantic settings)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env", "../../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["local", "test", "staging", "production"] = "local"
    app_name: str = "intelligent-bpm"
    api_version: str = "0.1.0"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173"

    database_url: str | None = Field(default=None)
    redis_url: str | None = Field(default=None)
    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_service_role_key: str | None = None
    supabase_jwt_secret: str | None = None
    supabase_jwt_audience: str = "authenticated"

    workflow_mode: Literal["mock", "temporal"] = "mock"
    temporal_host: str | None = None
    temporal_namespace: str | None = None
    temporal_api_key: str | None = None
    temporal_task_queue: str = "bpm-process"
    skip_dependency_checks: bool = False
    # memory = in-process store (tests/local without DB); postgres = SQLAlchemy
    persistence_mode: Literal["memory", "postgres"] = "memory"

    organization_header: str = "X-Organization-Id"
    idempotency_header: str = "Idempotency-Key"

    # Vertex AI / Gemini (official Google Gen AI Python SDK)
    google_cloud_project: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "google_cloud_project",
            "gcp_project_id",
            "gcp_project",
            "project_id",
        ),
    )
    google_cloud_location: str = Field(
        default="us-central1",
        validation_alias=AliasChoices(
            "google_cloud_location",
            "gcp_location",
            "gcp_region",
        ),
    )
    google_genai_use_vertexai: bool = True
    google_application_credentials: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "google_application_credentials",
            "gcp_application_credentials",
        ),
    )

    gemini_planner_model: str | None = None
    gemini_resource_model: str | None = None
    gemini_risk_model: str | None = None
    gemini_execution_model: str | None = None
    gemini_embedding_model: str | None = None
    gemini_model_id: str | None = None
    gemini_fallback_model: str | None = None

    gemini_temperature: float = 0.2
    gemini_max_output_tokens: int = 16384
    gemini_timeout_seconds: float = 90.0
    gemini_retry_count: int = 3
    gemini_circuit_failure_threshold: int = 5
    gemini_circuit_reset_seconds: float = 60.0
    gemini_client_mode: Literal["auto", "vertex", "fake"] = "auto"

    # Integration providers (mock by default; real only when credentials present)
    integrations_mode: Literal["mock", "auto"] = "mock"
    integrations_secret_key: str | None = None
    app_signing_secret: str | None = None
    email_provider: str | None = None  # smtp | resend | mock
    email_api_key: str | None = None
    email_from_address: str | None = None
    email_smtp_host: str | None = None
    email_smtp_port: int = 587
    email_smtp_username: str | None = None
    email_smtp_password: str | None = None
    email_smtp_use_tls: bool = True
    supplier_api_base_url: str | None = None
    supplier_api_key: str | None = None
    purchasing_api_base_url: str | None = None
    purchasing_api_key: str | None = None
    billing_api_base_url: str | None = None
    billing_api_key: str | None = None
    billing_webhook_secret: str | None = None

    # Production hardening
    content_security_policy: str | None = None
    csp_report_only: bool = False
    max_request_bytes: int = 1_048_576  # 1 MiB JSON/API default
    max_upload_bytes: int = 25 * 1024 * 1024  # 25 MiB files
    rate_limit_per_minute: int = 120
    login_max_failures: int = 10
    login_window_seconds: float = 300.0
    outbound_url_allowlist: str = (
        "localhost,127.0.0.1,example.supabase.co,storage.googleapis.com,"
        "mail.mock.local,suppliers.mock.local,purchasing.mock.local"
    )
    enable_csrf: bool = True
    enable_rate_limit: bool = True

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _strip_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def outbound_allowlist_hosts(self) -> frozenset[str]:
        return frozenset(
            h.strip().lower()
            for h in self.outbound_url_allowlist.split(",")
            if h.strip()
        )

    def effective_rate_limit_per_minute(self) -> int:
        if self.app_env == "test":
            return max(self.rate_limit_per_minute, 10_000)
        return self.rate_limit_per_minute

    def gemini_configured(self) -> bool:
        return bool(self.google_cloud_project) and bool(
            self.gemini_planner_model
            or self.gemini_resource_model
            or self.gemini_risk_model
            or self.gemini_execution_model
            or self.gemini_model_id
        )

    def missing_required_for_runtime(self) -> list[str]:
        missing: list[str] = []
        if self.persistence_mode == "postgres" and not self.database_url:
            missing.append("DATABASE_URL")
        if not self.redis_url:
            missing.append("REDIS_URL")
        if not self.supabase_url:
            missing.append("SUPABASE_URL")
        # JWT secret is preferred; Auth API fallback needs anon key when secret is absent
        if not self.supabase_jwt_secret and not self.supabase_anon_key:
            missing.append("SUPABASE_JWT_SECRET")
        return missing


class SettingsValidationError(Exception):
    def __init__(self, message: str, *, missing: list[str] | None = None) -> None:
        super().__init__(message)
        self.missing = missing or []


def validate_settings_or_raise(*, require_runtime_deps: bool = True) -> Settings:
    import os

    try:
        if os.environ.get("BPM_LOAD_DOTENV", "1") == "0" or os.environ.get("APP_ENV") == "test":
            settings = Settings(_env_file=None)
        else:
            settings = Settings()
    except ValidationError as exc:
        raise SettingsValidationError(
            "Environment validation failed. Check required variables in .env.example.",
            missing=[str(err["loc"][0]) for err in exc.errors() if err.get("loc")],
        ) from exc

    if require_runtime_deps and not settings.skip_dependency_checks:
        missing = settings.missing_required_for_runtime()
        if missing:
            raise SettingsValidationError(
                "Environment validation failed: missing required settings: "
                + ", ".join(missing),
                missing=missing,
            )
    return settings


@lru_cache
def get_settings() -> Settings:
    import os

    # Tests must not pick up the developer machine's real .env
    if os.environ.get("BPM_LOAD_DOTENV", "1") == "0" or os.environ.get("APP_ENV") == "test":
        return Settings(_env_file=None)
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
