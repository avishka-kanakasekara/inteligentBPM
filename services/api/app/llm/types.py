"""Shared types for the Gemini / Vertex AI runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID


class AgentKind(StrEnum):
    PLANNER = "planner"
    RESOURCE = "resource"
    RISK = "risk"
    EXECUTION = "execution"
    EMBEDDING = "embedding"


class LLMFailureKind(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    QUOTA = "quota"
    SAFETY_BLOCK = "safety_block"
    INVALID_JSON = "invalid_json"
    VALIDATION_ERROR = "validation_error"
    MODEL_UNAVAILABLE = "model_unavailable"
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    CIRCUIT_OPEN = "circuit_open"
    FORBIDDEN_TOOL = "forbidden_tool"
    TOOL_DENIED = "tool_denied"


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model_id: str | None = None
    agent: AgentKind | None = None

    def add(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            model_id=other.model_id or self.model_id,
            agent=other.agent or self.agent,
        )


@dataclass
class ModelCallMetadata:
    model_id: str
    agent: AgentKind
    latency_ms: float
    usage: TokenUsage
    request_labels: dict[str, str] = field(default_factory=dict)
    finish_reason: str | None = None
    fallback_used: bool = False
    attempt: int = 1


@dataclass
class EvidenceRef:
    """Stored separately from model text — never chain-of-thought."""

    type: str
    id: str
    label: str | None = None


@dataclass
class StructuredGenerationResult:
    data: Any
    metadata: ModelCallMetadata
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    raw_text: str | None = None  # JSON text only; never CoT


@dataclass
class ToolProposal:
    name: str
    arguments: dict[str, Any]
    thought_signature: str | None = None  # SDK-required opaque blob when present


@dataclass
class ToolResult:
    name: str
    ok: bool
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class GeminiMessage:
    role: str  # user | model | tool
    text: str | None = None
    tool_proposals: list[ToolProposal] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass
class GenerateRequest:
    model_id: str
    agent: AgentKind
    messages: list[GeminiMessage]
    system_instruction: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    response_schema: dict[str, Any] | None = None
    response_mime_type: str | None = None
    tools: list[dict[str, Any]] | None = None
    labels: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float | None = None


@dataclass
class GenerateResponse:
    text: str | None
    tool_proposals: list[ToolProposal] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    finish_reason: str | None = None
    blocked: bool = False
    block_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class EmbedRequest:
    model_id: str
    texts: list[str]
    labels: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float | None = None


@dataclass
class EmbedResponse:
    vectors: list[list[float]]
    usage: TokenUsage = field(default_factory=TokenUsage)
    model_id: str | None = None


@dataclass
class AgentExecutionContext:
    """Server-resolved identity and tracing for every agent call."""

    organization_id: UUID
    process_id: UUID | None
    correlation_id: str | None
    trace_id: str | None
    actor_user_id: UUID | None
    agent: AgentKind
    permissions: frozenset[str] = field(default_factory=frozenset)
    approval_snapshot_id: UUID | None = None
    plan_version_id: UUID | None = None
    labels: dict[str, str] = field(default_factory=dict)

    def request_labels(self) -> dict[str, str]:
        base = {
            "organization_id": str(self.organization_id),
            "agent": self.agent.value,
        }
        if self.process_id:
            base["process_id"] = str(self.process_id)
        if self.correlation_id:
            base["correlation_id"] = self.correlation_id
        if self.trace_id:
            base["trace_id"] = self.trace_id
        base.update(self.labels)
        return base
