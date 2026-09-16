"""Model ID registry — configuration only, never hardcoded preview IDs."""

from __future__ import annotations

from app.config.settings import Settings, get_settings
from app.llm.failures import LLMError
from app.llm.types import AgentKind, LLMFailureKind


class ModelRegistry:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def resolve(self, agent: AgentKind, *, allow_fallback: bool = True) -> str:
        mapping = {
            AgentKind.PLANNER: self.settings.gemini_planner_model,
            AgentKind.RESOURCE: self.settings.gemini_resource_model,
            AgentKind.RISK: self.settings.gemini_risk_model,
            AgentKind.EXECUTION: self.settings.gemini_execution_model,
            AgentKind.EMBEDDING: self.settings.gemini_embedding_model,
        }
        model = mapping.get(agent) or self.settings.gemini_model_id
        if not model and allow_fallback:
            model = self.settings.gemini_fallback_model
        if not model:
            raise LLMError(
                f"No model configured for agent {agent.value}. "
                "Set GEMINI_*_MODEL environment variables (do not hardcode preview IDs).",
                kind=LLMFailureKind.MODEL_UNAVAILABLE,
                retryable=False,
            )
        self._assert_not_preview_hardcode(model)
        return model

    def fallback(self, agent: AgentKind) -> str | None:
        primary = None
        try:
            primary = self.resolve(agent, allow_fallback=False)
        except LLMError:
            primary = None
        fallback = self.settings.gemini_fallback_model or self.settings.gemini_model_id
        if fallback and fallback != primary:
            self._assert_not_preview_hardcode(fallback)
            return fallback
        return None

    @staticmethod
    def _assert_not_preview_hardcode(model_id: str) -> None:
        # Runtime may use whatever configured ID operators provide, including
        # preview IDs if explicitly set in env — but application code must never
        # embed preview strings. This guard only blocks empty/whitespace.
        if not model_id.strip():
            raise LLMError(
                "Model ID is empty",
                kind=LLMFailureKind.MODEL_UNAVAILABLE,
                retryable=False,
            )
