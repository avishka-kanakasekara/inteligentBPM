"""Unit tests for Gemini Vertex AI runtime (fake client — no Vertex credentials)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import BaseModel, Field

from app.config import reset_settings_cache
from app.llm.client import FakeGeminiClient, VertexGeminiClient, create_gemini_client
from app.llm.failures import LLMError, LLMFailureClassifier
from app.llm.model_registry import ModelRegistry
from app.llm.prompt_registry import PromptRegistry
from app.llm.retry import CircuitBreaker, LLMRetryPolicy
from app.llm.safety import SafetyConfiguration
from app.llm.structured import StructuredGenerationService
from app.llm.tool_calling import FORBIDDEN_TOOL_NAMES, ToolCallingService
from app.llm.types import (
    AgentExecutionContext,
    AgentKind,
    EvidenceRef,
    GenerateResponse,
    LLMFailureKind,
    TokenUsage,
    ToolProposal,
)
from app.llm.usage import TokenUsageService


class PlanDraft(BaseModel):
    goal: str
    steps: list[str] = Field(default_factory=list)
    reasoning_summary: str = ""
    confidence: float = 0.5


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("GEMINI_CLIENT_MODE", "fake")
    monkeypatch.setenv("GEMINI_PLANNER_MODEL", "gemini-2.0-flash-001")
    monkeypatch.setenv("GEMINI_RESOURCE_MODEL", "gemini-2.0-flash-001")
    monkeypatch.setenv("GEMINI_RISK_MODEL", "gemini-2.0-flash-001")
    monkeypatch.setenv("GEMINI_EXECUTION_MODEL", "gemini-2.0-flash-001")
    monkeypatch.setenv("GEMINI_EMBEDDING_MODEL", "text-embedding-005")
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "gemini-2.0-flash-001")
    monkeypatch.setenv("SKIP_DEPENDENCY_CHECKS", "true")
    reset_settings_cache()
    yield
    reset_settings_cache()


def _context(**kwargs: object) -> AgentExecutionContext:
    base = dict(
        organization_id=uuid4(),
        process_id=uuid4(),
        correlation_id="corr-1",
        trace_id="trace-1",
        actor_user_id=uuid4(),
        agent=AgentKind.PLANNER,
        permissions=frozenset({"execution.run", "processes.create"}),
    )
    base.update(kwargs)
    return AgentExecutionContext(**base)  # type: ignore[arg-type]


def test_create_client_uses_fake_in_test_env() -> None:
    client = create_gemini_client()
    assert isinstance(client, FakeGeminiClient)


def test_model_registry_routes_per_agent() -> None:
    registry = ModelRegistry()
    assert registry.resolve(AgentKind.PLANNER) == "gemini-2.0-flash-001"
    assert registry.resolve(AgentKind.EMBEDDING) == "text-embedding-005"


def test_model_registry_requires_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_PLANNER_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_MODEL_ID", raising=False)
    monkeypatch.delenv("GEMINI_FALLBACK_MODEL", raising=False)
    monkeypatch.setenv("GEMINI_RESOURCE_MODEL", "")
    monkeypatch.setenv("GEMINI_RISK_MODEL", "")
    monkeypatch.setenv("GEMINI_EXECUTION_MODEL", "")
    monkeypatch.setenv("GEMINI_EMBEDDING_MODEL", "")
    reset_settings_cache()
    with pytest.raises(LLMError) as exc:
        ModelRegistry().resolve(AgentKind.PLANNER)
    assert exc.value.kind == LLMFailureKind.MODEL_UNAVAILABLE


def test_prompt_registry_renders() -> None:
    system, user = PromptRegistry().render(
        AgentKind.PLANNER,
        "discover_plan",
        goal="Buy laptops",
        context="budget approved",
    )
    assert "Agent 1" in system
    assert "Buy laptops" in user


def test_structured_generation_validates_and_tracks_usage() -> None:
    fake = FakeGeminiClient()
    fake.enqueue_structured(
        {
            "goal": "Procure laptops",
            "steps": ["gather quotes", "approve"],
            "reasoning_summary": "Clear procurement need",
            "confidence": 0.8,
            "chain_of_thought": "SECRET COT MUST BE STRIPPED",
        }
    )
    usage = TokenUsageService()
    service = StructuredGenerationService(client=fake, usage=usage)
    ctx = _context()
    result = service.generate(
        context=ctx,
        output_model=PlanDraft,
        system_instruction="system",
        user_prompt="plan please",
        evidence_refs=[EvidenceRef(type="document", id="d1", label="RFQ")],
    )
    assert isinstance(result.data, PlanDraft)
    assert result.data.goal == "Procure laptops"
    assert "chain_of_thought" not in (result.raw_text or "")
    assert result.evidence_refs[0].id == "d1"
    assert result.metadata.model_id
    assert usage.total_tokens(ctx.organization_id) == 30


def test_structured_generation_rejects_invalid_json_then_retries() -> None:
    fake = FakeGeminiClient()
    fake.enqueue_structured("NOT JSON")
    fake.enqueue_structured(
        {"goal": "Ok", "steps": [], "reasoning_summary": "ok", "confidence": 0.5}
    )
    service = StructuredGenerationService(
        client=fake,
        retry=LLMRetryPolicy(max_attempts=3, base_delay_seconds=0),
    )
    result = service.generate(
        context=_context(),
        output_model=PlanDraft,
        system_instruction="s",
        user_prompt="u",
    )
    assert result.data.goal == "Ok"
    assert len(fake.calls) == 2


def test_structured_generation_rejects_schema_invalid() -> None:
    fake = FakeGeminiClient()
    fake.enqueue_structured({"goal": 123})  # wrong type
    fake.enqueue_structured({"goal": 123})
    fake.enqueue_structured({"goal": 123})
    service = StructuredGenerationService(
        client=fake,
        retry=LLMRetryPolicy(max_attempts=2, base_delay_seconds=0),
    )
    with pytest.raises(LLMError) as exc:
        service.generate(
            context=_context(),
            output_model=PlanDraft,
            system_instruction="s",
            user_prompt="u",
        )
    assert exc.value.kind in {
        LLMFailureKind.VALIDATION_ERROR,
        LLMFailureKind.INVALID_JSON,
    }


def test_failure_classifier_kinds() -> None:
    clf = LLMFailureClassifier()
    assert clf.classify(TimeoutError("deadline exceeded")).kind == LLMFailureKind.TIMEOUT
    assert clf.classify(RuntimeError("429 rate limit")).kind == LLMFailureKind.RATE_LIMIT
    assert clf.classify(RuntimeError("quota exceeded")).kind == LLMFailureKind.QUOTA
    assert clf.classify(RuntimeError("safety blocked")).kind == LLMFailureKind.SAFETY_BLOCK
    assert clf.classify(RuntimeError("model unavailable 503")).kind == (
        LLMFailureKind.MODEL_UNAVAILABLE
    )


def test_circuit_breaker_opens() -> None:
    breaker = CircuitBreaker(failure_threshold=2, reset_seconds=60)
    assert breaker.allow()
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.is_open
    assert not breaker.allow()


def test_safety_configuration_dicts() -> None:
    safety = SafetyConfiguration()
    items = safety.to_sdk_dicts()
    assert any(i["category"].startswith("HARM_") for i in items)


def test_tool_calling_forbids_sql_and_shell() -> None:
    service = ToolCallingService(client=FakeGeminiClient())
    ctx = _context(
        agent=AgentKind.EXECUTION,
        plan_version_id=uuid4(),
        approval_snapshot_id=uuid4(),
    )
    service.approved_snapshot_ids.add(ctx.approval_snapshot_id)  # type: ignore[arg-type]
    for name in ("execute_sql", "shell", "run_code", "fetch_url"):
        assert name in FORBIDDEN_TOOL_NAMES
        result = service.execute_tool(ToolProposal(name=name, arguments={}), ctx)
        assert result.ok is False
        assert result.error_code == LLMFailureKind.FORBIDDEN_TOOL.value


def test_tool_calling_validates_permission_tenant_approval_and_executes() -> None:
    fake = FakeGeminiClient()
    snapshot = uuid4()
    plan = uuid4()
    org = uuid4()
    employee = uuid4()
    ctx = _context(
        organization_id=org,
        agent=AgentKind.EXECUTION,
        plan_version_id=plan,
        approval_snapshot_id=snapshot,
        permissions=frozenset({"execution.run"}),
    )
    service = ToolCallingService(client=fake)
    service.approved_snapshot_ids.add(snapshot)

    # Missing approval
    service.approved_snapshot_ids.clear()
    denied = service.execute_tool(
        ToolProposal(
            name="send_email",
            arguments={
                "to_employee_id": str(employee),
                "subject": "Hi",
                "body": "Hello",
                "idempotency_key": "idem-12345678",
            },
        ),
        ctx,
    )
    assert denied.ok is False

    service.approved_snapshot_ids.add(snapshot)
    # Tenant mismatch
    mismatch = service.execute_tool(
        ToolProposal(
            name="send_email",
            arguments={
                "organization_id": str(uuid4()),
                "to_employee_id": str(employee),
                "subject": "Hi",
                "body": "Hello",
                "idempotency_key": "idem-12345678",
            },
        ),
        ctx,
    )
    assert mismatch.ok is False

    ok = service.execute_tool(
        ToolProposal(
            name="send_email",
            arguments={
                "to_employee_id": str(employee),
                "subject": "Hi",
                "body": "Hello",
                "idempotency_key": "idem-12345678",
            },
        ),
        ctx,
    )
    assert ok.ok is True
    assert ok.result and ok.result["mock"] is True


def test_tool_calling_loop_returns_validated_final_response() -> None:
    fake = FakeGeminiClient()
    snapshot = uuid4()
    employee = uuid4()
    fake.enqueue_tools(
        GenerateResponse(
            text=None,
            tool_proposals=[
                ToolProposal(
                    name="send_email",
                    arguments={
                        "to_employee_id": str(employee),
                        "subject": "Quote",
                        "body": "Please review",
                        "idempotency_key": "idem-abcdefgh",
                    },
                )
            ],
            usage=TokenUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        )
    )
    fake.enqueue_structured(
        {
            "status": "ok",
            "summary": "Email proposed and executed",
            "proposed_tool_names": ["send_email"],
            "reasoning_summary": "Notified stakeholder",
            "evidence_refs": [],
        }
    )
    ctx = _context(
        agent=AgentKind.EXECUTION,
        plan_version_id=uuid4(),
        approval_snapshot_id=snapshot,
        permissions=frozenset({"execution.run"}),
    )
    service = ToolCallingService(client=fake)
    service.approved_snapshot_ids.add(snapshot)
    result = service.run(
        context=ctx,
        system_instruction="propose tools",
        user_prompt="notify buyer",
    )
    assert result.data.status == "ok"
    assert "send_email" in result.data.proposed_tool_names
    assert result.metadata.usage.total_tokens >= 10


def test_vertex_client_requires_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "")
    monkeypatch.setenv("GEMINI_CLIENT_MODE", "vertex")
    reset_settings_cache()
    client = VertexGeminiClient()
    with pytest.raises(LLMError):
        client._get_client()


def test_agent_execution_context_labels() -> None:
    ctx = _context(labels={"env": "test"})
    labels = ctx.request_labels()
    assert labels["organization_id"] == str(ctx.organization_id)
    assert labels["agent"] == "planner"
    assert labels["env"] == "test"
