import type { ProcessSummary } from "@bpm/frontend-types";
import { describe, expect, it } from "vitest";
import { describeProcessActivity } from "./ProcessActivity";

function process(overrides: Partial<ProcessSummary> = {}): ProcessSummary {
  return {
    id: "33333333-3333-3333-3333-333333333301",
    name: "Laptop procurement",
    status: "draft",
    risk_level: null,
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

describe("describeProcessActivity", () => {
  it("prefers blocked risk, finished execution, and open runs over draft status", () => {
    expect(describeProcessActivity(process({ risk_decision: "BLOCKED" }))?.label).toBe("Blocked");
    expect(
      describeProcessActivity(process({ execution_status: "completed", approval_status: "approved" }))
        ?.label,
    ).toBe("Completed");
    expect(describeProcessActivity(process({ execution_status: "draft" }))?.label).toBe(
      "Run started",
    );
    expect(describeProcessActivity(process({ approval_status: "rejected" }))?.label).toBe(
      "Rejected",
    );
    expect(describeProcessActivity(process())).toBeNull();
  });
});
