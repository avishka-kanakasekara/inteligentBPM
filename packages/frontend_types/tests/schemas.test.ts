import { describe, expect, it } from "vitest";
import { ZodError } from "zod";
import {
  ApprovalSummarySchema,
  BillingSubscriptionSnapshotSchema,
  HealthResponseSchema,
  OrganizationSchema,
  ProcessSummarySchema,
} from "../src/index";

const hostedTenant = {
  id: "76ec608f-37a4-45fa-bb58-fb81c0710720",
  name: "",
  slug: "",
  plan_code: "",
  status: "",
  membership_role: "employee",
};

describe("organization schema", () => {
  it("parses a hosted tenant with a blank plan, name, and slug", () => {
    const parsed = OrganizationSchema.parse(hostedTenant);
    expect(parsed.id).toBe(hostedTenant.id);
    expect(parsed.name).toBe("");
    expect(parsed.slug).toBe("");
    expect(parsed.plan_code).toBeNull();
  });

  it("keeps a verified catalog plan", () => {
    const parsed = OrganizationSchema.parse({ ...hostedTenant, plan_code: "enterprise" });
    expect(parsed.plan_code).toBe("enterprise");
  });

  it("does not turn an unknown plan into a paid plan", () => {
    const result = OrganizationSchema.safeParse({ ...hostedTenant, plan_code: "ultra" });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error).toBeInstanceOf(ZodError);
    }
  });

  it("parses a billing snapshot with an unspecified plan", () => {
    const parsed = BillingSubscriptionSnapshotSchema.parse({
      organization_id: hostedTenant.id,
      plan_code: "",
      subscription: { id: "sub-1", status: "active", plan_code: "" },
      features: {},
      limits: {},
    });
    expect(parsed.plan_code).toBeNull();
    expect(parsed.plan_code).not.toBe("pro");
  });

  it("keeps a catalog plan on a billing snapshot", () => {
    const parsed = BillingSubscriptionSnapshotSchema.parse({
      organization_id: hostedTenant.id,
      plan_code: "pro",
    });
    expect(parsed.plan_code).toBe("pro");
  });

  it("rejects an invalid billing plan instead of assigning a paid plan", () => {
    const result = BillingSubscriptionSnapshotSchema.safeParse({
      organization_id: hostedTenant.id,
      plan_code: "ultra",
    });
    expect(result.success).toBe(false);
  });
});

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
