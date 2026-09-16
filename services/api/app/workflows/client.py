"""Workflow client — Temporal Cloud or durable mock (no local containers)."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from app.config import get_settings
from app.workflows.engine import MockDurableWorkflowEngine, get_mock_engine
from app.workflows.models import WorkflowInstance, WorkflowSignal


class WorkflowClient(Protocol):
    def start_process_workflow(
        self,
        *,
        organization_id: UUID,
        process_id: UUID,
        process_run_id: UUID,
        process_version_id: UUID | None = None,
        initiated_by_user_id: UUID | None = None,
        trace_id: str | None = None,
        context: dict[str, Any] | None = None,
        timeout_seconds: int | None = 86_400,
    ) -> WorkflowInstance: ...

    def signal(
        self,
        workflow_id: UUID,
        *,
        signal_type: str | WorkflowSignal,
        payload: dict[str, Any] | None = None,
        event_id: str | None = None,
    ) -> WorkflowInstance: ...

    def describe(self, workflow_id: UUID) -> WorkflowInstance: ...

    def history(self, workflow_id: UUID) -> list[dict[str, Any]]: ...

    def recover(self, workflow_id: UUID) -> WorkflowInstance: ...


class MockWorkflowClient:
    """Managed-equivalent mock client backed by durable in-process engine."""

    def __init__(self, engine: MockDurableWorkflowEngine | None = None) -> None:
        self.engine = engine or get_mock_engine()

    def start_process_workflow(
        self,
        *,
        organization_id: UUID,
        process_id: UUID,
        process_run_id: UUID,
        process_version_id: UUID | None = None,
        initiated_by_user_id: UUID | None = None,
        trace_id: str | None = None,
        context: dict[str, Any] | None = None,
        timeout_seconds: int | None = 86_400,
    ) -> WorkflowInstance:
        return self.engine.start(
            organization_id=organization_id,
            process_id=process_id,
            process_run_id=process_run_id,
            process_version_id=process_version_id,
            initiated_by_user_id=initiated_by_user_id,
            trace_id=trace_id,
            context=context,
            timeout_seconds=timeout_seconds,
        )

    def signal(
        self,
        workflow_id: UUID,
        *,
        signal_type: str | WorkflowSignal,
        payload: dict[str, Any] | None = None,
        event_id: str | None = None,
    ) -> WorkflowInstance:
        return self.engine.signal(
            workflow_id,
            signal_type=signal_type,
            payload=payload,
            event_id=event_id,
        )

    def describe(self, workflow_id: UUID) -> WorkflowInstance:
        return self.engine.get(workflow_id)

    def history(self, workflow_id: UUID) -> list[dict[str, Any]]:
        return self.engine.history(workflow_id)

    def recover(self, workflow_id: UUID) -> WorkflowInstance:
        return self.engine.recover(workflow_id)


class TemporalWorkflowClient:
    """
    Temporal Cloud client.

    Requires TEMPORAL_HOST, TEMPORAL_NAMESPACE, and optionally TEMPORAL_API_KEY.
    Uses the official temporalio SDK when installed; does not start local containers.
    """

    def __init__(self) -> None:
        settings = get_settings()
        host = getattr(settings, "temporal_host", None)
        namespace = getattr(settings, "temporal_namespace", None)
        # Settings may not yet expose all temporal fields — read from env via WorkerSettings pattern
        from os import getenv

        self.host = host or getenv("TEMPORAL_HOST")
        self.namespace = namespace or getenv("TEMPORAL_NAMESPACE")
        self.api_key = getenv("TEMPORAL_API_KEY")
        self.task_queue = getenv("TEMPORAL_TASK_QUEUE", "bpm-process")
        if not self.host or not self.namespace:
            raise RuntimeError(
                "WORKFLOW_MODE=temporal requires TEMPORAL_HOST and TEMPORAL_NAMESPACE "
                "(Temporal Cloud). Use WORKFLOW_MODE=mock for local development without Docker."
            )
        self._client: Any = None

    async def connect(self) -> Any:
        try:
            from temporalio.client import Client
        except ImportError as exc:
            raise RuntimeError(
                "temporalio package is required for WORKFLOW_MODE=temporal. "
                "Install with: pip install temporalio"
            ) from exc

        if self.api_key:
            self._client = await Client.connect(
                self.host,
                namespace=self.namespace,
                api_key=self.api_key,
                tls=True,
            )
        else:
            self._client = await Client.connect(self.host, namespace=self.namespace)
        return self._client

    def start_process_workflow(self, **kwargs: Any) -> WorkflowInstance:
        # Sync facade: Temporal Cloud starts are async; bridge via temporal_bridge helpers.
        from app.workflows.temporal_bridge import start_via_temporal

        return start_via_temporal(self, **kwargs)

    def signal(self, workflow_id: UUID, **kwargs: Any) -> WorkflowInstance:
        from app.workflows.temporal_bridge import signal_via_temporal

        return signal_via_temporal(self, workflow_id, **kwargs)

    def describe(self, workflow_id: UUID) -> WorkflowInstance:
        from app.workflows.temporal_bridge import describe_via_temporal

        return describe_via_temporal(self, workflow_id)

    def history(self, workflow_id: UUID) -> list[dict[str, Any]]:
        from app.workflows.temporal_bridge import history_via_temporal

        return history_via_temporal(self, workflow_id)

    def recover(self, workflow_id: UUID) -> WorkflowInstance:
        # Temporal Cloud recovers automatically; mirror describe.
        return self.describe(workflow_id)


def get_workflow_client() -> WorkflowClient:
    settings = get_settings()
    if settings.workflow_mode == "temporal":
        return TemporalWorkflowClient()
    return MockWorkflowClient()
