"""Workflow definition versioning and recovery migration helpers."""

from __future__ import annotations

from typing import Any

# Bump when process graph / activity contracts change incompatibly.
WORKFLOW_DEFINITION_VERSION = "bpm.process.v1"

SUPPORTED_WORKFLOW_VERSIONS: frozenset[str] = frozenset(
    {
        "bpm.process.v1",
    }
)


class WorkflowVersionError(RuntimeError):
    """Raised when a persisted workflow cannot be recovered under the current definition."""


def assert_recoverable(version: str) -> None:
    if version not in SUPPORTED_WORKFLOW_VERSIONS:
        raise WorkflowVersionError(
            f"Unsupported workflow version {version!r}; "
            f"supported={sorted(SUPPORTED_WORKFLOW_VERSIONS)}"
        )


def migrate_workflow_state(state: dict[str, Any]) -> dict[str, Any]:
    """
    Migrate checkpointed workflow state forward to WORKFLOW_DEFINITION_VERSION.

    Currently a no-op identity for v1; extend with version-to-version transformers.
    """
    version = str(state.get("workflow_version") or WORKFLOW_DEFINITION_VERSION)
    assert_recoverable(version)
    migrated = dict(state)
    migrated["workflow_version"] = WORKFLOW_DEFINITION_VERSION
    return migrated
