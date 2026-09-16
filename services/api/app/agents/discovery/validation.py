"""Deterministic validation of Agent 1 plans (outside the LLM)."""

from __future__ import annotations

from app.agents.discovery.models import ProcessPlan
from app.llm.tool_calling import FORBIDDEN_TOOL_NAMES
from app.security.errors import ValidationAppError

FORBIDDEN_CLAIM_PHRASES = (
    "process is safe",
    "fully compliant",
    "bypass risk",
    "skip agent 3",
    "no approval needed for everything",
)


def validate_process_plan(plan: ProcessPlan) -> ProcessPlan:
    """Reject invalid plans. Does not invent data or execute side effects."""
    errors: list[str] = []

    if plan.claims_process_safe or plan.bypasses_risk_agent or plan.executes_side_effects:
        errors.append(
            "Agent 1 must not claim the process is safe, bypass Agent 3, or execute side effects"
        )

    step_ids = [s.step_id for s in plan.steps]
    if len(step_ids) != len(set(step_ids)):
        errors.append("Step IDs must be unique")

    known = set(step_ids)
    for step in plan.steps:
        for dep in step.dependencies:
            if dep not in known:
                errors.append(f"Step {step.step_id} depends on unknown step {dep}")
        for tool in step.allowed_tools:
            if tool.lower() in FORBIDDEN_TOOL_NAMES or tool in FORBIDDEN_TOOL_NAMES:
                errors.append(f"Step {step.step_id} lists forbidden tool {tool}")
            if tool.lower() in {"execute_sql", "shell", "run_code", "http_request"}:
                errors.append(f"Step {step.step_id} must not allow side-effect tool {tool}")
        if not step.success_criteria:
            errors.append(f"Step {step.step_id} requires success_criteria")
        if not step.description.strip():
            errors.append(f"Step {step.step_id} requires description")

    for edge in plan.edges:
        if edge.from_step_id not in known or edge.to_step_id not in known:
            errors.append(f"Edge {edge.edge_id} references unknown steps")
        if edge.from_step_id == edge.to_step_id:
            errors.append(f"Edge {edge.edge_id} cannot be self-referential")

    # Cycle detection on dependency graph
    if _has_cycle(plan):
        errors.append("Plan contains a dependency cycle")

    blob = (plan.goal + " " + plan.reasoning_summary).lower()
    for phrase in FORBIDDEN_CLAIM_PHRASES:
        if phrase in blob:
            errors.append(f"Plan text contains forbidden claim: {phrase}")

    if errors:
        raise ValidationAppError(
            "Invalid process plan",
            details={"errors": errors},
        )
    return plan


def _has_cycle(plan: ProcessPlan) -> bool:
    graph = {s.step_id: list(s.dependencies) for s in plan.steps}
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for dep in graph.get(node, []):
            if dep in graph and dfs(dep):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(dfs(node) for node in graph)


def ensure_stable_step_ids(
    new_plan: ProcessPlan,
    previous: ProcessPlan | None,
) -> ProcessPlan:
    """Preserve step IDs across revisions when titles match previous steps."""
    if previous is None:
        return new_plan
    by_title = {s.title.strip().lower(): s.step_id for s in previous.steps}
    remapped: dict[str, str] = {}
    for step in new_plan.steps:
        key = step.title.strip().lower()
        if key in by_title:
            remapped[step.step_id] = by_title[key]
            step.step_id = by_title[key]
    for step in new_plan.steps:
        step.dependencies = [remapped.get(d, d) for d in step.dependencies]
    for edge in new_plan.edges:
        edge.from_step_id = remapped.get(edge.from_step_id, edge.from_step_id)
        edge.to_step_id = remapped.get(edge.to_step_id, edge.to_step_id)
    return new_plan
