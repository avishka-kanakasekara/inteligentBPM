"""Alert rule evaluation over in-process metrics (no external alertmanager required)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.observability.metrics import (
    M_API_ERRORS,
    M_API_LATENCY,
    M_API_REQUESTS,
    M_APPROVAL_BACKLOG,
    M_CROSS_TENANT,
    M_GEMINI_FAILURES,
    M_GEMINI_REQUESTS,
    M_PROCESS_FAILURES,
    M_PROCESS_RUNS,
    M_TOKEN_USAGE,
    M_TOOL_FAILURE,
    M_TOOL_SUCCESS,
    M_WORKER_BACKLOG,
    metrics,
)


def _refresh_backlog_gauges() -> None:
    """Sample in-process queues for backlog alerts (native workers, no sidecars)."""
    try:
        from app.database.memory import get_memory_store
        from app.domain.enums import ApprovalStatus, ProcessRunStatus

        store = get_memory_store()
        approval_pending = sum(
            1
            for a in store.approvals.values()
            if getattr(a, "status", None) in {ApprovalStatus.PENDING, "pending"}
        )
        worker_backlog = 0
        for raw in getattr(store, "workflow_instances", {}).values():
            status = raw.get("status") if isinstance(raw, dict) else getattr(raw, "status", None)
            if status in {"running", "waiting"}:
                worker_backlog += 1
        if worker_backlog == 0:
            worker_backlog = sum(
                1
                for r in store.process_runs.values()
                if getattr(r, "status", None)
                in {
                    ProcessRunStatus.RUNNING,
                    ProcessRunStatus.AWAITING_APPROVAL,
                    "running",
                    "awaiting_approval",
                }
            )
        metrics.set(M_APPROVAL_BACKLOG, float(approval_pending))
        metrics.set(M_WORKER_BACKLOG, float(worker_backlog))
    except Exception:  # noqa: BLE001
        pass


@dataclass(frozen=True)
class Alert:
    name: str
    severity: str  # info | warning | critical
    message: str
    value: float
    threshold: float


def _counter_sum(prefix: str) -> float:
    snap = metrics.snapshot()["counters"]
    total = 0.0
    for key, value in snap.items():
        if key == prefix or key.startswith(prefix + "{"):
            total += float(value)
    return total


def _hist_avg(prefix: str) -> float:
    snap = metrics.snapshot()["histograms"]
    count = 0
    total = 0.0
    for key, value in snap.items():
        if key == prefix or key.startswith(prefix + "{"):
            count += int(value.get("count") or 0)
            total += float(value.get("sum_ms") or 0)
    return (total / count) if count else 0.0


def evaluate_alerts(
    *,
    api_error_rate_threshold: float = 0.05,
    api_latency_ms_threshold: float = 2000.0,
    workflow_failure_rate_threshold: float = 0.1,
    llm_failure_rate_threshold: float = 0.15,
    tool_failure_rate_threshold: float = 0.2,
    worker_backlog_threshold: float = 100.0,
    approval_backlog_threshold: float = 50.0,
    cross_tenant_threshold: float = 5.0,
    token_usage_threshold: float = 5_000_000.0,
) -> list[Alert]:
    _refresh_backlog_gauges()
    alerts: list[Alert] = []

    requests = _counter_sum(M_API_REQUESTS)
    errors = _counter_sum(M_API_ERRORS)
    if requests >= 20:
        rate = errors / requests
        if rate >= api_error_rate_threshold:
            alerts.append(
                Alert(
                    name="api_error_rate",
                    severity="critical",
                    message="API error rate above threshold",
                    value=rate,
                    threshold=api_error_rate_threshold,
                )
            )

    latency = _hist_avg(M_API_LATENCY)
    if latency >= api_latency_ms_threshold:
        alerts.append(
            Alert(
                name="api_latency",
                severity="warning",
                message="API latency average above threshold",
                value=latency,
                threshold=api_latency_ms_threshold,
            )
        )

    runs = _counter_sum(M_PROCESS_RUNS)
    failures = _counter_sum(M_PROCESS_FAILURES)
    if runs >= 10:
        wr = failures / runs
        if wr >= workflow_failure_rate_threshold:
            alerts.append(
                Alert(
                    name="workflow_failure_rate",
                    severity="critical",
                    message="Workflow failure rate above threshold",
                    value=wr,
                    threshold=workflow_failure_rate_threshold,
                )
            )

    gemini_req = _counter_sum(M_GEMINI_REQUESTS)
    gemini_fail = _counter_sum(M_GEMINI_FAILURES)
    if gemini_req >= 10:
        lr = gemini_fail / gemini_req
        if lr >= llm_failure_rate_threshold:
            alerts.append(
                Alert(
                    name="llm_failures",
                    severity="critical",
                    message="LLM failure rate above threshold",
                    value=lr,
                    threshold=llm_failure_rate_threshold,
                )
            )
            alerts.append(
                Alert(
                    name="provider_outages",
                    severity="warning",
                    message="Elevated Gemini provider failures (possible outage)",
                    value=lr,
                    threshold=llm_failure_rate_threshold,
                )
            )

    tool_ok = _counter_sum(M_TOOL_SUCCESS)
    tool_fail = _counter_sum(M_TOOL_FAILURE)
    tool_total = tool_ok + tool_fail
    if tool_total >= 10:
        tr = tool_fail / tool_total
        if tr >= tool_failure_rate_threshold:
            alerts.append(
                Alert(
                    name="repeated_tool_failures",
                    severity="warning",
                    message="Tool failure rate above threshold",
                    value=tr,
                    threshold=tool_failure_rate_threshold,
                )
            )

    backlog = _counter_sum(M_WORKER_BACKLOG)
    if backlog >= worker_backlog_threshold:
        alerts.append(
            Alert(
                name="worker_backlog",
                severity="warning",
                message="Worker backlog above threshold",
                value=backlog,
                threshold=worker_backlog_threshold,
            )
        )

    approval_backlog = _counter_sum(M_APPROVAL_BACKLOG)
    if approval_backlog >= approval_backlog_threshold:
        alerts.append(
            Alert(
                name="approval_backlog",
                severity="warning",
                message="Approval backlog above threshold",
                value=approval_backlog,
                threshold=approval_backlog_threshold,
            )
        )

    cross = _counter_sum(M_CROSS_TENANT)
    if cross >= cross_tenant_threshold:
        alerts.append(
            Alert(
                name="suspicious_tenant_access",
                severity="critical",
                message="Repeated cross-tenant authorization failures",
                value=cross,
                threshold=cross_tenant_threshold,
            )
        )

    tokens = _counter_sum(M_TOKEN_USAGE)
    if tokens >= token_usage_threshold:
        alerts.append(
            Alert(
                name="excessive_token_usage",
                severity="warning",
                message="Token usage above threshold",
                value=tokens,
                threshold=token_usage_threshold,
            )
        )

    return alerts


def alerts_as_dicts() -> list[dict[str, Any]]:
    return [
        {
            "name": a.name,
            "severity": a.severity,
            "message": a.message,
            "value": a.value,
            "threshold": a.threshold,
        }
        for a in evaluate_alerts()
    ]
