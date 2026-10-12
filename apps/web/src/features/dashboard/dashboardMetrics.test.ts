import type { ApprovalSummary, ProcessRun, ProcessSummary } from "@bpm/frontend-types";
import { describe, expect, it } from "vitest";
import { selectDashboardMetrics } from "./dashboardMetrics";

function process(overrides: Partial<ProcessSummary> = {}): ProcessSummary {
  return {
    id: "33333333-3333-3333-3333-333333333301",
    name: "Laptop procurement",
    status: "draft",
    risk_level: "medium",
    approval_status: null,
    execution_status: null,
    missing_information: [],
    unresolved_assignments: [],
    policy_evidence: [],
    source_refs: [],
    recommendations: [],
    human_decision: null,
    updated_at: "2026-10-11T00:00:00.000Z",
    ...overrides,
  };
}

function run(overrides: Partial<ProcessRun> = {}): ProcessRun {
  return {
    id: "55555555-5555-5555-5555-555555555501",
    organization_id: "11111111-1111-1111-1111-111111111111",
    process_id: "33333333-3333-3333-3333-333333333301",
    status: "completed",
    created_at: "2026-10-11T00:00:00.000Z",
    dry_run: false,
    current_step_index: 1,
    pause_reason: null,
    ...overrides,
  };
}

describe("selectDashboardMetrics", () => {
  it("counts open runs, finished executions, pending approvals, and blocked risk", () => {
    const metrics = selectDashboardMetrics(
      [
        process({ execution_status: "completed" }),
        process({
          id: "33333333-3333-3333-3333-333333333302",
          name: "Blocked spend",
          risk_decision: "BLOCKED",
          risk_level: "critical",
        }),
        process({
          id: "33333333-3333-3333-3333-333333333303",
          name: "Still drafting",
          execution_status: "draft",
        }),
      ],
      [
        run(),
        run({
          id: "55555555-5555-5555-5555-555555555502",
          process_id: "33333333-3333-3333-3333-333333333301",
          status: "completed",
        }),
        run({
          id: "55555555-5555-5555-5555-555555555503",
          process_id: "33333333-3333-3333-3333-333333333303",
          status: "draft",
        }),
        run({
          id: "55555555-5555-5555-5555-555555555504",
          status: "cancelled",
        }),
      ],
      [
        {
          id: "44444444-4444-4444-4444-444444444401",
          process_id: "33333333-3333-3333-3333-333333333301",
          status: "pending",
        } as ApprovalSummary,
        {
          id: "44444444-4444-4444-4444-444444444402",
          process_id: "33333333-3333-3333-3333-333333333309",
          status: "approved",
        } as ApprovalSummary,
      ],
    );

    expect(metrics.activeRuns).toBe(1);
    expect(metrics.completed).toBe(2);
    expect(metrics.pendingApprovals).toBe(1);
    expect(metrics.blocked).toBe(1);
    expect(metrics.blockedProcessIds).toEqual(["33333333-3333-3333-3333-333333333302"]);
  });
});
