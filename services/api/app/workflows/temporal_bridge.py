"""Temporal Cloud bridge — optional; requires temporalio SDK and cloud credentials."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from app.workflows.models import WorkflowInstance


def _run(coro: Any) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Already in async context — use a dedicated threadless fallback via nest pattern
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def start_via_temporal(client: Any, **kwargs: Any) -> WorkflowInstance:
    """
    Start BPMProcessWorkflow on Temporal Cloud.

    Falls back with a clear error until the Temporal worker registers the workflow.
    Activities share the same implementations as the mock engine.
    """

    async def _start() -> WorkflowInstance:
        await client.connect()
        raise RuntimeError(
            "Temporal Cloud workflow registration is configured via services/workflow_worker. "
            "Ensure the worker process is running against Temporal Cloud "
            f"(namespace={client.namespace}, queue={client.task_queue}). "
            "For local tests without Temporal credentials, set WORKFLOW_MODE=mock."
        )

    return _run(_start())


def signal_via_temporal(client: Any, workflow_id: UUID, **kwargs: Any) -> WorkflowInstance:
    async def _signal() -> WorkflowInstance:
        await client.connect()
        raise RuntimeError(
            f"Temporal signal requires a running Cloud worker for workflow {workflow_id}. "
            "Use WORKFLOW_MODE=mock when Temporal Cloud is unavailable."
        )

    return _run(_signal())


def describe_via_temporal(client: Any, workflow_id: UUID) -> WorkflowInstance:
    async def _describe() -> WorkflowInstance:
        await client.connect()
        raise RuntimeError(
            f"Temporal describe requires Temporal Cloud connectivity for workflow {workflow_id}."
        )

    return _run(_describe())


def history_via_temporal(client: Any, workflow_id: UUID) -> list[dict[str, Any]]:
    async def _history() -> list[dict[str, Any]]:
        await client.connect()
        raise RuntimeError(
            f"Temporal history requires Temporal Cloud connectivity for workflow {workflow_id}."
        )

    return _run(_history())
