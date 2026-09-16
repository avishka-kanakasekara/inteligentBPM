"""Tool-calling service with backend validation and allowlisted execution."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError

from app.llm.client import GeminiClient, create_gemini_client
from app.llm.failures import LLMError, LLMFailureClassifier
from app.llm.logging import log_llm_event
from app.llm.model_registry import ModelRegistry
from app.llm.retry import CircuitBreaker, LLMRetryPolicy
from app.llm.types import (
    AgentExecutionContext,
    AgentKind,
    GeminiMessage,
    GenerateRequest,
    GenerateResponse,
    LLMFailureKind,
    ModelCallMetadata,
    StructuredGenerationResult,
    TokenUsage,
    ToolProposal,
    ToolResult,
)
from app.llm.usage import TokenUsageService, get_token_usage_service

# ---------------------------------------------------------------------------
# Hard bans — never expose these as callable tools
# ---------------------------------------------------------------------------
FORBIDDEN_TOOL_NAMES = frozenset(
    {
        "execute_sql",
        "run_sql",
        "sql",
        "shell",
        "bash",
        "run_shell",
        "exec",
        "eval",
        "execute_code",
        "run_code",
        "http_request",
        "fetch_url",
        "open_url",
        "arbitrary_network",
        "db_query",
        "database",
        "psql",
        "kubectl",
    }
)

FORBIDDEN_ARG_KEYS = frozenset(
    {"sql", "query_sql", "shell", "command", "code", "script", "url", "endpoint", "raw_http"}
)


class SendEmailArgs(BaseModel):
    to_employee_id: UUID
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class RequestQuotationArgs(BaseModel):
    supplier_id: UUID
    product_sku: str = Field(min_length=1, max_length=100)
    quantity: int = Field(gt=0, le=100000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class CreatePurchaseOrderDraftArgs(BaseModel):
    supplier_id: UUID
    amount_total: float = Field(gt=0)
    currency_code: str = Field(min_length=3, max_length=3)
    idempotency_key: str = Field(min_length=8, max_length=128)


@dataclass
class ToolDefinition:
    name: str
    description: str
    args_model: type[BaseModel]
    required_permission: str
    requires_approval: bool = True
    handler: Callable[[BaseModel, AgentExecutionContext], dict[str, Any]] | None = None


def _mock_email(args: BaseModel, ctx: AgentExecutionContext) -> dict[str, Any]:
    assert isinstance(args, SendEmailArgs)
    return {
        "mock": True,
        "status": "queued",
        "to_employee_id": str(args.to_employee_id),
        "organization_id": str(ctx.organization_id),
    }


def _mock_rfq(args: BaseModel, ctx: AgentExecutionContext) -> dict[str, Any]:
    assert isinstance(args, RequestQuotationArgs)
    return {
        "mock": True,
        "status": "requested",
        "supplier_id": str(args.supplier_id),
        "organization_id": str(ctx.organization_id),
    }


def _mock_po(args: BaseModel, ctx: AgentExecutionContext) -> dict[str, Any]:
    assert isinstance(args, CreatePurchaseOrderDraftArgs)
    return {
        "mock": True,
        "status": "draft",
        "supplier_id": str(args.supplier_id),
        "organization_id": str(ctx.organization_id),
    }


DEFAULT_TOOLS: dict[str, ToolDefinition] = {
    "send_email": ToolDefinition(
        name="send_email",
        description="Send an email to an employee via the tool gateway (mock or provider).",
        args_model=SendEmailArgs,
        required_permission="execution.run",
        requires_approval=True,
        handler=_mock_email,
    ),
    "request_quotation": ToolDefinition(
        name="request_quotation",
        description="Request a supplier quotation through the gateway.",
        args_model=RequestQuotationArgs,
        required_permission="execution.run",
        requires_approval=True,
        handler=_mock_rfq,
    ),
    "create_purchase_order_draft": ToolDefinition(
        name="create_purchase_order_draft",
        description="Create an internal PO draft (no external submit without approval).",
        args_model=CreatePurchaseOrderDraftArgs,
        required_permission="execution.run",
        requires_approval=True,
        handler=_mock_po,
    ),
}


class FinalToolCallingOutput(BaseModel):
    """Final structured response after any tool loop."""

    status: str
    summary: str
    proposed_tool_names: list[str] = Field(default_factory=list)
    reasoning_summary: str = ""
    evidence_refs: list[dict[str, str]] = Field(default_factory=list)


@dataclass
class ToolCallingService:
    """
    Gemini may propose tools; backend validates name, args, tenant, permissions,
    plan authorization, and approvals before execution. Results return to Gemini;
    final response is validated. Forbidden: SQL, shell, code, arbitrary network/URLs/DB.
    """

    client: GeminiClient = field(default_factory=create_gemini_client)
    models: ModelRegistry = field(default_factory=ModelRegistry)
    retry: LLMRetryPolicy = field(default_factory=LLMRetryPolicy)
    circuit: CircuitBreaker = field(default_factory=CircuitBreaker)
    usage: TokenUsageService = field(default_factory=get_token_usage_service)
    tools: dict[str, ToolDefinition] = field(default_factory=lambda: dict(DEFAULT_TOOLS))
    classifier: LLMFailureClassifier = field(default_factory=LLMFailureClassifier)
    approved_snapshot_ids: set[UUID] = field(default_factory=set)
    max_tool_rounds: int = 3

    def allowlist_schemas(self) -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for tool in self.tools.values():
            schemas.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.args_model.model_json_schema(),
                }
            )
        return schemas

    def validate_proposal(
        self,
        proposal: ToolProposal,
        context: AgentExecutionContext,
    ) -> tuple[ToolDefinition, BaseModel]:
        name = proposal.name.strip()
        if name in FORBIDDEN_TOOL_NAMES or name.lower() in FORBIDDEN_TOOL_NAMES:
            raise LLMError(
                f"Forbidden tool name: {name}",
                kind=LLMFailureKind.FORBIDDEN_TOOL,
                retryable=False,
            )
        if name not in self.tools:
            raise LLMError(
                f"Unknown tool: {name}",
                kind=LLMFailureKind.FORBIDDEN_TOOL,
                retryable=False,
            )
        # Reject dangerous argument keys even if somehow present
        for key in proposal.arguments:
            if key.lower() in FORBIDDEN_ARG_KEYS:
                raise LLMError(
                    f"Forbidden tool argument: {key}",
                    kind=LLMFailureKind.FORBIDDEN_TOOL,
                    retryable=False,
                    details={"tool": name, "argument": key},
                )
            value = proposal.arguments[key]
            if isinstance(value, str) and key.lower() in {"url", "uri", "href"}:
                raise LLMError(
                    "Arbitrary URLs are not allowed in tool arguments",
                    kind=LLMFailureKind.FORBIDDEN_TOOL,
                    retryable=False,
                )

        tool = self.tools[name]
        if tool.required_permission not in context.permissions:
            raise LLMError(
                f"Missing permission {tool.required_permission} for tool {name}",
                kind=LLMFailureKind.TOOL_DENIED,
                retryable=False,
            )
        # Tenant scope: tools must not accept foreign organization_id
        client_org = proposal.arguments.get("organization_id")
        if client_org is not None and str(client_org) != str(context.organization_id):
            raise LLMError(
                "Tool argument organization_id does not match tenant scope",
                kind=LLMFailureKind.TOOL_DENIED,
                retryable=False,
            )
        # Process-plan authorization
        if context.plan_version_id is None and context.agent == AgentKind.EXECUTION:
            raise LLMError(
                "Execution tool calls require an authorized plan_version_id",
                kind=LLMFailureKind.TOOL_DENIED,
                retryable=False,
            )
        # Approvals
        if tool.requires_approval:
            if (
                context.approval_snapshot_id is None
                or context.approval_snapshot_id not in self.approved_snapshot_ids
            ):
                raise LLMError(
                    "Tool requires a valid approved snapshot",
                    kind=LLMFailureKind.TOOL_DENIED,
                    retryable=False,
                    details={"tool": name},
                )

        try:
            args = tool.args_model.model_validate(proposal.arguments)
        except ValidationError as exc:
            raise LLMError(
                f"Invalid tool arguments for {name}",
                kind=LLMFailureKind.VALIDATION_ERROR,
                retryable=False,
                details={"errors": exc.errors()},
            ) from exc
        return tool, args

    def execute_tool(
        self,
        proposal: ToolProposal,
        context: AgentExecutionContext,
    ) -> ToolResult:
        try:
            tool, args = self.validate_proposal(proposal, context)
        except LLMError as exc:
            log_llm_event(
                "llm.tool_denied",
                tool=proposal.name,
                kind=exc.kind.value,
                message=exc.message,
                organization_id=str(context.organization_id),
            )
            return ToolResult(
                name=proposal.name,
                ok=False,
                error_code=exc.kind.value,
                error_message=exc.message,
            )
        handler = tool.handler
        if handler is None:
            return ToolResult(
                name=tool.name,
                ok=False,
                error_code="NO_HANDLER",
                error_message="Tool handler not configured",
            )
        result = handler(args, context)
        # Validate tool result shape lightly
        if not isinstance(result, dict):
            return ToolResult(
                name=tool.name,
                ok=False,
                error_code="INVALID_RESULT",
                error_message="Tool result must be an object",
            )
        if str(result.get("organization_id", context.organization_id)) != str(
            context.organization_id
        ):
            return ToolResult(
                name=tool.name,
                ok=False,
                error_code="TENANT_MISMATCH",
                error_message="Tool result violated tenant scope",
            )
        log_llm_event(
            "llm.tool_executed",
            tool=tool.name,
            organization_id=str(context.organization_id),
            mock=bool(result.get("mock")),
        )
        return ToolResult(name=tool.name, ok=True, result=result)

    def run(
        self,
        *,
        context: AgentExecutionContext,
        system_instruction: str,
        user_prompt: str,
        output_model: type[FinalToolCallingOutput] = FinalToolCallingOutput,
    ) -> StructuredGenerationResult:
        if not self.circuit.allow():
            raise LLMError(
                "LLM circuit breaker is open",
                kind=LLMFailureKind.CIRCUIT_OPEN,
                retryable=False,
            )

        model_id = self.models.resolve(context.agent)
        messages: list[GeminiMessage] = [GeminiMessage(role="user", text=user_prompt)]
        executed_names: list[str] = []
        total_usage = TokenUsage(model_id=model_id, agent=context.agent)
        started = time.perf_counter()

        for _round in range(self.max_tool_rounds):
            response = self._generate_round(
                model_id=model_id,
                context=context,
                system_instruction=system_instruction,
                messages=messages,
            )
            total_usage = total_usage.add(response.usage)
            if response.tool_proposals:
                results: list[ToolResult] = []
                for proposal in response.tool_proposals:
                    result = self.execute_tool(proposal, context)
                    results.append(result)
                    if result.ok:
                        executed_names.append(proposal.name)
                messages.append(
                    GeminiMessage(role="model", tool_proposals=response.tool_proposals)
                )
                messages.append(GeminiMessage(role="tool", tool_results=results))
                continue

            # Final text response — validate
            text = (response.text or "").strip() or "{}"
            import json

            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise LLMError(
                    "Final tool-calling response was not valid JSON",
                    kind=LLMFailureKind.INVALID_JSON,
                    retryable=True,
                ) from exc
            if isinstance(payload, dict):
                payload.setdefault("proposed_tool_names", executed_names)
                payload.setdefault("status", "ok" if executed_names else "no_tools")
                payload.pop("chain_of_thought", None)
            try:
                data = output_model.model_validate(payload)
            except ValidationError as exc:
                raise LLMError(
                    "Final response failed validation",
                    kind=LLMFailureKind.VALIDATION_ERROR,
                    retryable=True,
                    details={"errors": exc.errors()},
                ) from exc

            self.usage.record(
                organization_id=context.organization_id,
                agent=context.agent,
                model_id=model_id,
                usage=total_usage,
                correlation_id=context.correlation_id,
                process_id=context.process_id,
            )
            self.circuit.record_success()
            latency_ms = (time.perf_counter() - started) * 1000
            try:
                from app.observability.metrics import M_AGENT_LATENCY, metrics

                metrics.observe(M_AGENT_LATENCY, latency_ms, agent=context.agent.value)
            except Exception:  # noqa: BLE001
                pass
            metadata = ModelCallMetadata(
                model_id=model_id,
                agent=context.agent,
                latency_ms=latency_ms,
                usage=total_usage,
                request_labels=context.request_labels(),
                finish_reason=response.finish_reason,
            )
            return StructuredGenerationResult(
                data=data,
                metadata=metadata,
                evidence_refs=[],
                raw_text=text,
            )

        try:
            from app.observability.metrics import M_GEMINI_FAILURES, metrics

            metrics.incr(M_GEMINI_FAILURES, agent=context.agent.value)
        except Exception:  # noqa: BLE001
            pass
        raise LLMError(
            "Tool-calling loop exceeded max rounds without a final response",
            kind=LLMFailureKind.PERMANENT,
            retryable=False,
        )

    def _generate_round(
        self,
        *,
        model_id: str,
        context: AgentExecutionContext,
        system_instruction: str,
        messages: list[GeminiMessage],
    ) -> GenerateResponse:
        attempt = 0
        while True:
            attempt += 1
            try:
                return self.client.generate(
                    GenerateRequest(
                        model_id=model_id,
                        agent=context.agent,
                        messages=messages,
                        system_instruction=system_instruction,
                        tools=self.allowlist_schemas(),
                        response_mime_type="application/json",
                        response_schema=FinalToolCallingOutput.model_json_schema(),
                        labels=context.request_labels(),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                error = self.classifier.classify(exc)
                self.circuit.record_failure()
                if self.retry.should_retry(error, attempt):
                    time.sleep(self.retry.delay_seconds(attempt))
                    continue
                try:
                    from app.observability.metrics import M_GEMINI_FAILURES, metrics

                    metrics.incr(M_GEMINI_FAILURES, agent=context.agent.value)
                except Exception:  # noqa: BLE001
                    pass
                raise error from exc
