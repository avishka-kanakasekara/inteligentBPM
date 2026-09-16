"""Structured JSON generation with schema validation and safe retries."""

from __future__ import annotations

import json
import time
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.client import GeminiClient, create_gemini_client
from app.llm.failures import LLMError, LLMFailureClassifier
from app.llm.logging import log_llm_event
from app.llm.model_registry import ModelRegistry
from app.llm.retry import CircuitBreaker, LLMRetryPolicy
from app.llm.types import (
    AgentExecutionContext,
    EvidenceRef,
    GeminiMessage,
    GenerateRequest,
    LLMFailureKind,
    ModelCallMetadata,
    StructuredGenerationResult,
    TokenUsage,
)
from app.llm.usage import TokenUsageService, get_token_usage_service

T = TypeVar("T", bound=BaseModel)


class StructuredGenerationService:
    """
    Every structured agent call:
    1) Pydantic output model  2) JSON schema  3) structured JSON request
    4) parse  5) validate  6) reject invalid  7) retry safely
    8) store model metadata + usage  9) evidence refs separate  10) no CoT storage
    """

    def __init__(
        self,
        client: GeminiClient | None = None,
        *,
        models: ModelRegistry | None = None,
        retry: LLMRetryPolicy | None = None,
        circuit: CircuitBreaker | None = None,
        usage: TokenUsageService | None = None,
    ) -> None:
        self.client = client or create_gemini_client()
        self.models = models or ModelRegistry()
        self.retry = retry or LLMRetryPolicy()
        self.circuit = circuit or CircuitBreaker()
        self.usage = usage or get_token_usage_service()
        self.classifier = LLMFailureClassifier()

    def generate(
        self,
        *,
        context: AgentExecutionContext,
        output_model: type[T],
        system_instruction: str,
        user_prompt: str,
        evidence_refs: list[EvidenceRef] | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> StructuredGenerationResult:
        if not self.circuit.allow():
            raise LLMError(
                "LLM circuit breaker is open",
                kind=LLMFailureKind.CIRCUIT_OPEN,
                retryable=False,
            )

        schema = output_model.model_json_schema()
        primary = self.models.resolve(context.agent)
        fallback = self.models.fallback(context.agent)
        model_id = primary
        fallback_used = False
        attempt = 0
        last_error: LLMError | None = None

        while True:
            attempt += 1
            started = time.perf_counter()
            try:
                response = self.client.generate(
                    GenerateRequest(
                        model_id=model_id,
                        agent=context.agent,
                        messages=[GeminiMessage(role="user", text=user_prompt)],
                        system_instruction=system_instruction,
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                        response_schema=schema,
                        response_mime_type="application/json",
                        labels=context.request_labels(),
                    )
                )
                if response.blocked:
                    raise self.classifier.from_blocked(response.block_reason)

                text = (response.text or "").strip()
                if not text:
                    raise LLMError(
                        "Empty model response",
                        kind=LLMFailureKind.INVALID_JSON,
                        retryable=True,
                    )
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise LLMError(
                        f"Invalid JSON from model: {exc}",
                        kind=LLMFailureKind.INVALID_JSON,
                        retryable=True,
                    ) from exc

                # Never persist chain-of-thought / hidden reasoning fields
                if isinstance(payload, dict):
                    for banned in ("chain_of_thought", "cot", "private_reasoning", "scratchpad"):
                        payload.pop(banned, None)

                try:
                    data = output_model.model_validate(payload)
                except ValidationError as exc:
                    raise LLMError(
                        f"Response failed schema validation: {exc.error_count()} error(s)",
                        kind=LLMFailureKind.VALIDATION_ERROR,
                        retryable=True,
                        details={"errors": exc.errors()},
                    ) from exc

                # Store sanitized JSON only — never hidden chain-of-thought
                safe_text = json.dumps(payload)

                latency_ms = (time.perf_counter() - started) * 1000
                usage = response.usage or TokenUsage()
                usage.model_id = model_id
                usage.agent = context.agent
                self.usage.record(
                    organization_id=context.organization_id,
                    agent=context.agent,
                    model_id=model_id,
                    usage=usage,
                    correlation_id=context.correlation_id,
                    process_id=context.process_id,
                )
                metadata = ModelCallMetadata(
                    model_id=model_id,
                    agent=context.agent,
                    latency_ms=latency_ms,
                    usage=usage,
                    request_labels=context.request_labels(),
                    finish_reason=response.finish_reason,
                    fallback_used=fallback_used,
                    attempt=attempt,
                )
                self.circuit.record_success()
                try:
                    from app.observability.metrics import M_AGENT_LATENCY, metrics

                    metrics.observe(M_AGENT_LATENCY, latency_ms, agent=context.agent.value)
                except Exception:  # noqa: BLE001
                    pass
                log_llm_event(
                    "llm.structured_success",
                    model_id=model_id,
                    agent=context.agent.value,
                    organization_id=str(context.organization_id),
                    latency_ms=latency_ms,
                    total_tokens=usage.total_tokens,
                )
                # Evidence refs stored separately from model prose
                return StructuredGenerationResult(
                    data=data,
                    metadata=metadata,
                    evidence_refs=list(evidence_refs or []),
                    raw_text=safe_text,
                )
            except Exception as exc:  # noqa: BLE001
                error = self.classifier.classify(exc)
                last_error = error
                self.circuit.record_failure()
                log_llm_event(
                    "llm.structured_failure",
                    model_id=model_id,
                    agent=context.agent.value,
                    kind=error.kind.value,
                    message=error.message,
                    attempt=attempt,
                )
                if self.retry.should_retry(error, attempt):
                    time.sleep(self.retry.delay_seconds(attempt))
                    continue
                if (
                    error.kind in {
                        LLMFailureKind.MODEL_UNAVAILABLE,
                        LLMFailureKind.TIMEOUT,
                        LLMFailureKind.RATE_LIMIT,
                    }
                    and fallback
                    and model_id != fallback
                ):
                    model_id = fallback
                    fallback_used = True
                    attempt = 0
                    continue
                try:
                    from app.observability.metrics import M_GEMINI_FAILURES, metrics

                    metrics.incr(M_GEMINI_FAILURES, agent=context.agent.value)
                except Exception:  # noqa: BLE001
                    pass
                raise error from exc

        assert last_error is not None
        raise last_error
