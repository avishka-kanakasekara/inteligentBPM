import { describe, expect, it } from "vitest";
import {
  ApprovalSummarySchema,
  HealthResponseSchema,
  ProcessSummarySchema,
} from "../src/index";

describe("frontend-types", () => {
  it("parses health responses", () => {
    const parsed = HealthResponseSchema.parse({
      status: "ok",
      service: "api",
      version: "0.1.0",
    });
    expect(parsed.status).toBe("ok");
  });

  it("accepts backend source_ref types including user", () => {
    const parsed = ProcessSummarySchema.parse({
      id: "1023397b-4ebe-4d4e-90af-6dac3eaae330",
      name: "Laptop procurement",
      status: "draft",
      risk_level: null,
      approval_status: null,
      execution_status: null,
      missing_information: [],
      unresolved_assignments: [],
      policy_evidence: [],
      source_refs: [
        { type: "user", id: "msg-1", label: null },
        { type: "chunk", id: "c1", label: "RFQ notes" },
      ],
      recommendations: [],
      human_decision: null,
      updated_at: new Date().toISOString(),
    });
    expect(parsed.source_refs[0]).toEqual({
      type: "user",
      id: "msg-1",
      label: "",
    });
    expect(parsed.source_refs[1].type).toBe("chunk");
    expect(parsed.has_allocation).toBe(false);
  });

  it("allows nullish enrichment fields on approval summaries", () => {
    const parsed = ApprovalSummarySchema.parse({
      id: "1e810629-7631-44e1-a588-73fb62586a7f",
      process_id: null,
      process_name: "Monitor bundle buy",
      status: "pending",
      risk_level: "medium",
      risk_decision: null,
      required_roles: [],
      snapshot_hash: "abc",
      plan_snapshot_hash: null,
      risk_snapshot_hash: null,
      policy_evidence: [],
      source_refs: [],
      decision_note: null,
      risk_summary: null,
      risk_items: null,
    });
    expect(parsed.status).toBe("pending");
    expect(parsed.risk_items).toBeNull();
  });
});
