"""Worker settings."""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "intelligent-bpm-worker"
    workflow_mode: Literal["mock", "temporal"] = "mock"
    log_level: str = "INFO"
    temporal_host: str | None = None
    temporal_namespace: str | None = None
    temporal_api_key: str | None = None
    temporal_task_queue: str = "bpm-process"
