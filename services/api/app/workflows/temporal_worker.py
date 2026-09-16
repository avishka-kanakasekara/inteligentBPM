"""Temporal Cloud workflow/activity registration stubs.

Full activity implementations live in app.workflows.activities.
When temporalio is installed and WORKFLOW_MODE=temporal, the worker registers these.
"""

from __future__ import annotations

from typing import Any

# Placeholder list — Temporal worker imports these symbols.
BPM_ACTIVITIES: list[Any] = []


class BPMProcessTemporalWorkflow:
    """
    Temporal workflow class placeholder.

    The durable mock engine (MockDurableWorkflowEngine) implements the same
    process graph for local/tests. Register a real @workflow.defn class here
    when deploying against Temporal Cloud with temporalio installed.
    """

    @staticmethod
    def run(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError(
            "Deploy BPMProcessTemporalWorkflow with @workflow.defn when using Temporal Cloud"
        )
