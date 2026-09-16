"""Health and readiness response contracts."""

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = Field(..., description="Logical service name")
    version: str = Field(..., description="Service or platform version")


class ReadinessCheck(BaseModel):
    name: str
    ready: bool
    detail: str | None = None


class ReadinessResponse(BaseModel):
    ready: bool
    service: str
    checks: list[ReadinessCheck] = Field(default_factory=list)
