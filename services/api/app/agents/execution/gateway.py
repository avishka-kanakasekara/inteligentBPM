"""Tool gateway — validates and executes allowlisted tools only."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.agents.execution.adapters import (
    ProviderFailure,
    adapters_from_bundle,
)
from app.agents.execution.catalog import TOOL_ARGS, TOOL_CATALOG
from app.agents.execution.models import (
    ApprovalType,
    IdempotencyBehavior,
    SideEffectStatus,
    ToolContext,
    ToolDefinition,
    ToolError,
    ToolErrorCode,
    ToolInvocation,
    ToolResult,
)
from app.agents.execution.quotations import (
    compare_quotations,
    extract_quotation_from_text,
    normalize_quotation,
)
from app.agents.execution.url_allowlist import sanitize_outbound_urls
from app.audit import AuditService
from app.contracts.common import utcnow
from app.database.memory import get_memory_store, new_id
from app.domain.enums import ApprovalStatus
from app.llm.tool_calling import FORBIDDEN_ARG_KEYS, FORBIDDEN_TOOL_NAMES
from app.repositories.memory_repos import (
    EmployeeManagerLinkRepository,
    EmployeeRepository,
    IdempotencyRepository,
    PolicyRepository,
    SupplierContactRepository,
    SupplierRepository,
)
from app.services.documents.pipeline import DocumentSearchService


class ToolGatewayError(Exception):
    def __init__(self, error: ToolError) -> None:
        super().__init__(error.message)
        self.error = error


class ToolGateway:
    """
    Single door for side effects. Execution sequence:
    verify run/status/snapshots/risk/approvals → allowlist → authz →
    idempotency → provider → persist → audit → advance.
    """

    def __init__(self, *, force_provider_failure: bool = False) -> None:
        self.catalog = dict(TOOL_CATALOG)
        (
            self.email,
            self.suppliers,
            self.purchasing,
            self.notifications,
            self.calendar,
            self.tasks,
            self.documents,
        ) = adapters_from_bundle()
        self.audit = AuditService()
        self.idempotency = IdempotencyRepository()
        self.force_provider_failure = force_provider_failure

    def get_definition(self, name: str) -> ToolDefinition | None:
        return self.catalog.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        return list(self.catalog.values())

    def invoke(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        context: ToolContext,
        skip_run_checks: bool = False,
    ) -> ToolInvocation:
        started = time.perf_counter()
        store = get_memory_store()
        invocation_id = new_id()
        now = utcnow()

        try:
            if not skip_run_checks:
                self._verify_run_and_snapshots(context)
            tool = self._verify_allowlist_and_forbidden(tool_name, context)
            self._verify_authorization(tool, context)
            args = self._validate_args(tool_name, arguments)
            idem_key = getattr(args, "idempotency_key", None)
            self._verify_approval_gate(tool, context)
            request_hash = hashlib.sha256(
                json.dumps(
                    {"tool": tool_name, "args": arguments},
                    sort_keys=True,
                    default=str,
                ).encode()
            ).hexdigest()

            if tool.idempotency_behavior != IdempotencyBehavior.NONE:
                if not idem_key:
                    raise ToolGatewayError(
                        ToolError(
                            code=ToolErrorCode.IDEMPOTENCY_REQUIRED,
                            message="Side-effecting tools require an idempotency key",
                        )
                    )
                existing = self.idempotency.get(
                    context.organization_id, f"tool:{tool_name}", idem_key
                )
                if existing and existing.status == "completed" and existing.response_body:
                    result = ToolResult.model_validate(existing.response_body)
                    inv = ToolInvocation(
                        id=invocation_id,
                        organization_id=context.organization_id,
                        process_id=context.process_id,
                        process_run_id=context.process_run_id,
                        tool_name=tool_name,
                        arguments=arguments,
                        idempotency_key=idem_key,
                        status="replayed",
                        result=result,
                        plan_snapshot_hash=context.plan_snapshot_hash,
                        risk_snapshot_hash=context.risk_snapshot_hash,
                        approval_id=context.approval_id,
                        created_at=now,
                        updated_at=utcnow(),
                    )
                    store.tool_invocations[invocation_id] = inv.model_dump(mode="json")
                    return inv
                self.idempotency.begin(
                    organization_id=context.organization_id,
                    scope=f"tool:{tool_name}",
                    key=idem_key,
                    request_hash=request_hash,
                )

            if context.dry_run:
                result = ToolResult(
                    ok=True,
                    tool_name=tool_name,
                    data={"dry_run": True, "would_execute": True, "arguments": args.model_dump()},
                    dry_run=True,
                    mock=True,
                    untrusted=True,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
                status = "dry_run"
            else:
                if self.force_provider_failure and tool.side_effect_status != SideEffectStatus.NONE:
                    raise ProviderFailure("Simulated provider failure", retryable=True)
                data = self._dispatch(tool_name, args, context)
                data = sanitize_outbound_urls(data)
                if not isinstance(data, dict):
                    raise ToolGatewayError(
                        ToolError(
                            code=ToolErrorCode.OUTPUT_INVALID,
                            message="Tool output must be an object",
                        )
                    )
                self._stamp_process_scope(data, context, tool_name=tool_name)
                result = ToolResult(
                    ok=True,
                    tool_name=tool_name,
                    data=data,
                    dry_run=False,
                    mock=bool(data.get("mock", True)),
                    untrusted=True,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
                status = "executed"

            if (
                tool.idempotency_behavior != IdempotencyBehavior.NONE
                and idem_key
                and not context.dry_run
            ):
                self.idempotency.complete(
                    organization_id=context.organization_id,
                    scope=f"tool:{tool_name}",
                    key=idem_key,
                    response_status=200,
                    response_body=result.model_dump(mode="json"),
                )

            inv = ToolInvocation(
                id=invocation_id,
                organization_id=context.organization_id,
                process_id=context.process_id,
                process_run_id=context.process_run_id,
                tool_name=tool_name,
                arguments=arguments,
                idempotency_key=idem_key,
                status=status,  # type: ignore[arg-type]
                result=result,
                plan_snapshot_hash=context.plan_snapshot_hash,
                risk_snapshot_hash=context.risk_snapshot_hash,
                approval_id=context.approval_id,
                created_at=now,
                updated_at=utcnow(),
            )
            store.tool_invocations[invocation_id] = inv.model_dump(mode="json")
            self.audit.record(
                organization_id=context.organization_id,
                actor_user_id=context.actor_user_id,
                action=f"tool.{status}",
                resource_type="tool_invocation",
                resource_id=invocation_id,
                correlation_id=context.correlation_id,
                payload={"tool": tool_name, "dry_run": context.dry_run},
            )
            try:
                from app.observability.metrics import M_TOOL_SUCCESS, metrics

                if status == "executed":
                    metrics.incr(M_TOOL_SUCCESS, tool=tool_name)
            except Exception:  # noqa: BLE001
                pass
            return inv

        except ToolGatewayError as exc:
            inv = ToolInvocation(
                id=invocation_id,
                organization_id=context.organization_id,
                process_id=context.process_id,
                process_run_id=context.process_run_id,
                tool_name=tool_name,
                arguments=arguments,
                status="denied" if exc.error.code != ToolErrorCode.PROVIDER_FAILURE else "failed",
                error=exc.error,
                result=ToolResult(
                    ok=False,
                    tool_name=tool_name,
                    error=exc.error,
                    latency_ms=(time.perf_counter() - started) * 1000,
                ),
                created_at=now,
                updated_at=utcnow(),
            )
            store.tool_invocations[invocation_id] = inv.model_dump(mode="json")
            self.audit.record(
                organization_id=context.organization_id,
                actor_user_id=context.actor_user_id,
                action="tool.denied",
                resource_type="tool_invocation",
                resource_id=invocation_id,
                correlation_id=context.correlation_id,
                payload={"tool": tool_name, "code": exc.error.code.value},
            )
            try:
                from app.observability.metrics import M_TOOL_FAILURE, metrics

                metrics.incr(M_TOOL_FAILURE, tool=tool_name)
            except Exception:  # noqa: BLE001
                pass
            return inv
        except ProviderFailure as exc:
            try:
                from app.observability.metrics import M_EMAIL_FAILURES, M_TOOL_FAILURE, metrics

                metrics.incr(M_TOOL_FAILURE, tool=tool_name)
                if tool_name.startswith("email."):
                    metrics.incr(M_EMAIL_FAILURES)
            except Exception:  # noqa: BLE001
                pass
            error = ToolError(
                code=ToolErrorCode.PROVIDER_FAILURE,
                message=str(exc),
                retryable=exc.retryable,
            )
            inv = ToolInvocation(
                id=invocation_id,
                organization_id=context.organization_id,
                process_id=context.process_id,
                process_run_id=context.process_run_id,
                tool_name=tool_name,
                arguments=arguments,
                status="failed",
                error=error,
                result=ToolResult(ok=False, tool_name=tool_name, error=error),
                created_at=now,
                updated_at=utcnow(),
            )
            store.tool_invocations[invocation_id] = inv.model_dump(mode="json")
            return inv
        except Exception as exc:  # noqa: BLE001
            error = ToolError(
                code=ToolErrorCode.PROVIDER_FAILURE,
                message=str(exc),
                retryable=True,
            )
            inv = ToolInvocation(
                id=invocation_id,
                organization_id=context.organization_id,
                process_id=context.process_id,
                process_run_id=context.process_run_id,
                tool_name=tool_name,
                arguments=arguments,
                status="failed",
                error=error,
                result=ToolResult(ok=False, tool_name=tool_name, error=error),
                created_at=now,
                updated_at=utcnow(),
            )
            store.tool_invocations[invocation_id] = inv.model_dump(mode="json")
            return inv

    # ------------------------------------------------------------------
    # Verification steps
    # ------------------------------------------------------------------

    def _verify_run_and_snapshots(self, context: ToolContext) -> None:
        store = get_memory_store()
        run = store.process_runs.get(context.process_run_id)
        if run is None or run.organization_id != context.organization_id:
            raise ToolGatewayError(
                ToolError(code=ToolErrorCode.TENANT_MISMATCH, message="Process run not found for tenant")
            )
        if run.process_id != context.process_id:
            raise ToolGatewayError(
                ToolError(code=ToolErrorCode.TENANT_MISMATCH, message="Process/run mismatch")
            )
        allowed_statuses = {
            "executing",
            "approved",
            "paused",
            "awaiting_approval",
            "draft",  # dry-run may start early
        }
        if run.status.value not in allowed_statuses and not context.dry_run:
            raise ToolGatewayError(
                ToolError(
                    code=ToolErrorCode.RUN_STATUS_INVALID,
                    message=f"Process run status {run.status.value} cannot execute tools",
                )
            )
        # Snapshot binding when present on run
        if getattr(run, "plan_snapshot_hash", None) and context.plan_snapshot_hash:
            if run.plan_snapshot_hash != context.plan_snapshot_hash:
                raise ToolGatewayError(
                    ToolError(
                        code=ToolErrorCode.SNAPSHOT_MISMATCH,
                        message="Approved plan snapshot hash mismatch",
                    )
                )
        if getattr(run, "risk_snapshot_hash", None) and context.risk_snapshot_hash:
            if run.risk_snapshot_hash != context.risk_snapshot_hash:
                raise ToolGatewayError(
                    ToolError(
                        code=ToolErrorCode.SNAPSHOT_MISMATCH,
                        message="Risk snapshot hash mismatch",
                    )
                )

    def _verify_allowlist_and_forbidden(
        self, tool_name: str, context: ToolContext
    ) -> ToolDefinition:
        if tool_name in FORBIDDEN_TOOL_NAMES or tool_name.lower() in FORBIDDEN_TOOL_NAMES:
            raise ToolGatewayError(
                ToolError(
                    code=ToolErrorCode.FORBIDDEN_TOOL,
                    message=f"Forbidden tool: {tool_name}",
                )
            )
        if tool_name not in self.catalog:
            raise ToolGatewayError(
                ToolError(code=ToolErrorCode.UNKNOWN_TOOL, message=f"Unknown tool: {tool_name}")
            )
        if context.allowed_tools and tool_name not in context.allowed_tools:
            raise ToolGatewayError(
                ToolError(
                    code=ToolErrorCode.ALLOWLIST_DENIED,
                    message=f"Tool {tool_name} not on process allowlist",
                )
            )
        return self.catalog[tool_name]

    def _verify_authorization(self, tool: ToolDefinition, context: ToolContext) -> None:
        if tool.required_permission not in context.permissions:
            raise ToolGatewayError(
                ToolError(
                    code=ToolErrorCode.UNAUTHORIZED,
                    message=f"Missing permission {tool.required_permission}",
                )
            )

    def _validate_args(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        for key in arguments:
            if key.lower() in FORBIDDEN_ARG_KEYS:
                raise ToolGatewayError(
                    ToolError(
                        code=ToolErrorCode.FORBIDDEN_TOOL,
                        message=f"Forbidden argument: {key}",
                    )
                )
            value = arguments[key]
            if isinstance(value, str) and (
                key.lower() in {"url", "uri", "href", "endpoint"}
                or value.startswith("http://")
                or value.startswith("https://")
            ):
                try:
                    sanitize_outbound_urls({key: value})
                except ValueError as exc:
                    raise ToolGatewayError(
                        ToolError(code=ToolErrorCode.URL_NOT_ALLOWED, message=str(exc))
                    ) from exc
        model = TOOL_ARGS[tool_name]
        try:
            return model.model_validate(arguments)
        except ValidationError as exc:
            raise ToolGatewayError(
                ToolError(
                    code=ToolErrorCode.VALIDATION_ERROR,
                    message=f"Invalid arguments for {tool_name}",
                    details={"errors": exc.errors()},
                )
            ) from exc

    def _verify_approval_gate(self, tool: ToolDefinition, context: ToolContext) -> None:
        # Read-only may execute without approval
        if tool.side_effect_status == SideEffectStatus.NONE:
            return
        # Draft-producing may execute with policy/snapshot as configured
        req = tool.approval_requirement
        if req is None or req.approval_type == ApprovalType.NONE:
            return
        if req.approval_type == ApprovalType.POLICY and tool.side_effect_status == SideEffectStatus.DRAFT:
            # Allowed according to policy when run is approved/executing or dry-run
            if context.dry_run:
                return
            if context.approval_id is None and not context.plan_snapshot_hash:
                # Soft gate: drafts need at least a plan snapshot on the run
                raise ToolGatewayError(
                    ToolError(
                        code=ToolErrorCode.APPROVAL_REQUIRED,
                        message="Draft tools require an approved plan snapshot context",
                    )
                )
            return
        if req.requires_approved_snapshot or req.irreversible or req.approval_type in {
            ApprovalType.EXPLICIT,
            ApprovalType.SNAPSHOT,
            ApprovalType.FINANCE,
        }:
            if context.dry_run:
                return
            if context.approval_id is None:
                raise ToolGatewayError(
                    ToolError(
                        code=ToolErrorCode.APPROVAL_REQUIRED,
                        message=f"Tool {tool.name} requires explicit approval",
                    )
                )
            store = get_memory_store()
            approval = store.approvals.get(context.approval_id)
            if approval is None or approval.organization_id != context.organization_id:
                raise ToolGatewayError(
                    ToolError(
                        code=ToolErrorCode.APPROVAL_INVALID,
                        message="Approval not found for tenant",
                    )
                )
            if approval.status != ApprovalStatus.APPROVED:
                raise ToolGatewayError(
                    ToolError(
                        code=ToolErrorCode.APPROVAL_REQUIRED,
                        message=f"Approval status is {approval.status.value}, not approved",
                    )
                )
            if approval.prohibited_action and not approval.override_required:
                raise ToolGatewayError(
                    ToolError(
                        code=ToolErrorCode.APPROVAL_INVALID,
                        message="Cannot execute prohibited action without override",
                    )
                )
            if (
                context.plan_snapshot_hash
                and approval.plan_snapshot_hash
                and approval.plan_snapshot_hash != context.plan_snapshot_hash
            ):
                raise ToolGatewayError(
                    ToolError(
                        code=ToolErrorCode.SNAPSHOT_MISMATCH,
                        message="Approval plan hash mismatch",
                    )
                )
            if (
                context.risk_snapshot_hash
                and approval.risk_snapshot_hash
                and approval.risk_snapshot_hash != context.risk_snapshot_hash
            ):
                raise ToolGatewayError(
                    ToolError(
                        code=ToolErrorCode.SNAPSHOT_MISMATCH,
                        message="Approval risk hash mismatch",
                    )
                )
            if (
                approval.process_run_id is not None
                and approval.process_run_id != context.process_run_id
            ):
                raise ToolGatewayError(
                    ToolError(
                        code=ToolErrorCode.APPROVAL_INVALID,
                        message="Approval cannot be reused for another process run",
                    )
                )

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _stamp_process_scope(
        self, data: dict[str, Any], context: ToolContext, *, tool_name: str
    ) -> None:
        """Attach process scope to tool output and backfill in-memory artifact stores."""
        data.setdefault("process_id", str(context.process_id))
        data.setdefault("process_run_id", str(context.process_run_id))
        store = get_memory_store()
        rid = data.get("id")
        if not rid:
            return
        try:
            key = UUID(str(rid))
        except Exception:
            return
        collections: list[dict] = []
        if tool_name == "notification.send":
            collections.append(store.notifications)
        elif tool_name == "calendar.create_event":
            collections.append(store.calendar_events)
        elif tool_name == "task.assign":
            collections.append(getattr(store, "tasks", {}) or {})
        elif tool_name == "document.generate":
            collections.append(getattr(store, "generated_documents", {}) or {})
        for collection in collections:
            record = collection.get(key)
            if isinstance(record, dict):
                record["process_id"] = str(context.process_id)
                record["process_run_id"] = str(context.process_run_id)
                collection[key] = record  # reassign so postgres persistence fires
                data["process_id"] = str(context.process_id)
                data["process_run_id"] = str(context.process_run_id)

    def _dispatch(self, tool_name: str, args: Any, context: ToolContext) -> dict[str, Any]:
        org = context.organization_id
        # Pass process scope into live side-effect tools when supported
        if tool_name in {
            "notification.send",
            "calendar.create_event",
            "task.assign",
            "document.generate",
            "supplier.request_quote",
        }:
            pass  # stamped after dispatch via _stamp_process_scope
        if tool_name == "company.employee_lookup":
            employees = EmployeeRepository(org).list_all()
            q = args.query.lower()
            hits = [
                {
                    "id": str(e.id),
                    "full_name": e.full_name,
                    "email": e.email,
                    "status": e.status,
                    "is_manager": e.is_manager,
                }
                for e in employees
                if e.organization_id == org
                and (q in e.full_name.lower() or q in e.email.lower())
            ]
            return {"employees": hits, "mock": False, "untrusted": False}

        if tool_name == "company.manager_lookup":
            emp_id = UUID(args.employee_id)
            EmployeeRepository(org).get(emp_id)
            links = EmployeeManagerLinkRepository(org).list_for_employee(emp_id)
            managers = []
            for link in links:
                if link.status != "active":
                    continue
                mgr = EmployeeRepository(org).get(link.manager_employee_id)
                managers.append(
                    {
                        "id": str(mgr.id),
                        "full_name": mgr.full_name,
                        "email": mgr.email,
                        "status": mgr.status,
                    }
                )
            return {"managers": managers, "mock": False}

        if tool_name == "supplier.search":
            q = args.query.lower()
            hits = []
            for s in SupplierRepository(org).list_all():
                if args.approved_only and (
                    s.approval_status != "approved" or s.status != "active"
                ):
                    continue
                if q in s.name.lower() or (s.code and q in s.code.lower()):
                    hits.append(
                        {
                            "id": str(s.id),
                            "name": s.name,
                            "approval_status": s.approval_status,
                            "status": s.status,
                        }
                    )
            return {"suppliers": hits, "mock": False}

        if tool_name == "supplier.contact_lookup":
            sid = UUID(args.supplier_id)
            SupplierRepository(org).get(sid)
            contacts = SupplierContactRepository(org).list_all(supplier_id=sid)
            return {
                "contacts": [
                    {
                        "id": str(c.id),
                        "full_name": c.full_name,
                        "email": c.email,
                        "status": c.status,
                    }
                    for c in contacts
                    if c.organization_id == org
                ],
                "mock": False,
            }

        if tool_name == "supplier.approved_status":
            s = SupplierRepository(org).get(UUID(args.supplier_id))
            return {
                "supplier_id": str(s.id),
                "approval_status": s.approval_status,
                "status": s.status,
                "approved": s.approval_status == "approved" and s.status == "active",
                "mock": False,
            }

        if tool_name == "policy.search":
            q = args.query.lower()
            hits = [
                {"id": str(p.id), "code": p.code, "title": p.title, "status": p.status}
                for p in PolicyRepository(org).list_all()
                if q in p.code.lower() or q in p.title.lower()
            ]
            return {"policies": hits, "mock": False}

        if tool_name == "document.search":
            hits = DocumentSearchService(org).search(
                query=args.query,
                limit=args.limit,
                can_read_restricted=True,
            )
            return {
                "hits": [
                    {
                        "chunk_id": str(h.chunk_id),
                        "document_id": str(h.document_id),
                        "excerpt": h.content[:400],
                        "score": h.score,
                        "untrusted": True,
                    }
                    for h in hits
                ],
                "mock": False,
                "untrusted": True,
            }

        if tool_name == "email.create_draft":
            return self.email.create_draft(
                organization_id=org,
                to_employee_id=args.to_employee_id,
                subject=args.subject,
                body=args.body,
                idempotency_key=args.idempotency_key,
            )

        if tool_name == "email.send":
            return self.email.send(
                organization_id=org,
                to_employee_id=args.to_employee_id,
                subject=args.subject,
                body=args.body,
                idempotency_key=args.idempotency_key,
                draft_id=args.draft_id,
            )

        if tool_name == "supplier.request_quote":
            kwargs = {
                "organization_id": org,
                "supplier_id": args.supplier_id,
                "product_sku": args.product_sku,
                "quantity": args.quantity,
                "idempotency_key": args.idempotency_key,
            }
            if getattr(args, "subject", None):
                kwargs["subject"] = args.subject
            if getattr(args, "body", None):
                kwargs["body"] = args.body
            if getattr(args, "contact_email", None):
                kwargs["contact_email"] = args.contact_email
            return self.suppliers.request_quote(**kwargs)

        if tool_name == "supplier.collect_quote":
            return self.suppliers.collect_quote(
                organization_id=org,
                request_id=args.request_id,
                idempotency_key=args.idempotency_key,
            )

        if tool_name == "quotation.extract":
            extracted = extract_quotation_from_text(
                args.raw_text, supplier_id=args.supplier_id
            )
            return {"quotation": extracted, "untrusted": True, "mock": True}

        if tool_name == "quotation.normalize":
            normalized = normalize_quotation(args.quotation)
            return {"quotation": normalized.model_dump(mode="json"), "mock": True}

        if tool_name == "quotation.compare":
            store = get_memory_store()
            quotes = []
            for qid in args.quotation_ids:
                raw = store.quotations.get(UUID(qid))
                if raw is None or raw.get("organization_id") != str(org):
                    continue
                quotes.append(normalize_quotation(raw))
            comparison = compare_quotations(quotes)
            if args.explain and quotes:
                # Gemini only explains — scoring already deterministic
                comparison.explanation = (
                    comparison.explanation
                    + " (Explanation assist available; scoring remains deterministic.)"
                )
            return comparison.model_dump(mode="json")

        if tool_name == "purchase_order.create_draft":
            return self.purchasing.create_draft(
                organization_id=org,
                supplier_id=args.supplier_id,
                amount_total=args.amount_total,
                currency_code=args.currency_code,
                lines=args.lines,
                idempotency_key=args.idempotency_key,
            )

        if tool_name == "purchase_order.submit":
            return self.purchasing.submit(
                organization_id=org,
                purchase_order_id=args.purchase_order_id,
                idempotency_key=args.idempotency_key,
            )

        if tool_name == "approval.request":
            return {
                "requested": True,
                "reason": args.reason,
                "required_roles": args.required_roles,
                "idempotency_key": args.idempotency_key,
                "mock": True,
                "checkpoint": True,
            }

        if tool_name == "notification.send":
            return self.notifications.send(
                organization_id=org,
                user_id=args.user_id,
                title=args.title,
                body=args.body,
                idempotency_key=args.idempotency_key,
            )

        if tool_name == "calendar.create_event":
            return self.calendar.create_event(
                organization_id=org,
                title=args.title,
                start_at=args.start_at,
                end_at=args.end_at,
                attendees=list(args.attendees or []),
                description=args.description or "",
                idempotency_key=args.idempotency_key,
            )

        if tool_name == "task.assign":
            return self.tasks.assign(
                organization_id=org,
                title=args.title,
                assignee_id=args.assignee_id,
                description=args.description or "",
                due_at=args.due_at,
                idempotency_key=args.idempotency_key,
            )

        if tool_name == "document.generate":
            return self.documents.generate(
                organization_id=org,
                title=args.title,
                doc_type=args.doc_type,
                content=args.content,
                idempotency_key=args.idempotency_key,
            )

        raise ToolGatewayError(
            ToolError(code=ToolErrorCode.UNKNOWN_TOOL, message=f"No handler for {tool_name}")
        )
