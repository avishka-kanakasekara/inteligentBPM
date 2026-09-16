"""Token usage tracking (in-memory foundation store)."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from uuid import UUID

from app.llm.types import AgentKind, TokenUsage


@dataclass
class UsageRecord:
    organization_id: UUID
    agent: AgentKind
    model_id: str
    usage: TokenUsage
    correlation_id: str | None = None
    process_id: UUID | None = None


@dataclass
class TokenUsageService:
    _records: list[UsageRecord] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)

    def record(
        self,
        *,
        organization_id: UUID,
        agent: AgentKind,
        model_id: str,
        usage: TokenUsage,
        correlation_id: str | None = None,
        process_id: UUID | None = None,
    ) -> UsageRecord:
        item = UsageRecord(
            organization_id=organization_id,
            agent=agent,
            model_id=model_id,
            usage=usage,
            correlation_id=correlation_id,
            process_id=process_id,
        )
        with self._lock:
            self._records.append(item)
        try:
            from app.observability.metrics import M_GEMINI_REQUESTS, M_TOKEN_USAGE, metrics

            metrics.incr(M_GEMINI_REQUESTS, agent=agent.value)
            metrics.incr(M_TOKEN_USAGE, value=float(usage.total_tokens), agent=agent.value)
        except Exception:  # noqa: BLE001
            pass
        return item

    def list_for_org(self, organization_id: UUID) -> list[UsageRecord]:
        with self._lock:
            return [r for r in self._records if r.organization_id == organization_id]

    def total_tokens(self, organization_id: UUID) -> int:
        return sum(r.usage.total_tokens for r in self.list_for_org(organization_id))

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


_USAGE = TokenUsageService()


def get_token_usage_service() -> TokenUsageService:
    return _USAGE
