import type {
  ApprovalSummary,
  AuditEvent,
  Budget,
  CostCenter,
  Department,
  Document,
  DocumentSearchResponse,
  Employee,
  ImportCommit,
  ImportPreview,
  Notification,
  Organization,
  OrganizationProfile,
  Policy,
  ProcessRun,
  ProcessSummary,
  Supplier,
  SupplierContact,
  SupplierProduct,
} from "@bpm/frontend-types";
import { ApiError } from "./apiClient";

const ORG_ID = "11111111-1111-1111-1111-111111111111";
const ORG_B = "22222222-2222-2222-2222-222222222222";

const ORGS: Organization[] = [
  {
    id: ORG_ID,
    name: "Demo Organization",
    slug: "demo-organization",
    plan_code: "pro",
    status: "active",
    membership_role: "owner",
  },
  {
    id: ORG_B,
    name: "Acme Enterprise",
    slug: "acme-enterprise",
    plan_code: "enterprise",
    status: "active",
    membership_role: "manager",
  },
];

const PROCESSES: ProcessSummary[] = [
  {
    id: "33333333-3333-3333-3333-333333333301",
    name: "Laptop procurement",
    status: "awaiting_approval",
    risk_level: "medium",
    approval_status: "pending",
    execution_status: null,
    missing_information: ["Preferred supplier SLA"],
    unresolved_assignments: ["Step 3 — Finance reviewer"],
    policy_evidence: ["PROC-001 §2 purchase thresholds"],
    source_refs: [
      { type: "policy", id: "p1", label: "Procurement Approval Policy" },
      { type: "document", id: "d1", label: "Laptop RFQ notes" },
    ],
    recommendations: ["Request dual quotes before approval"],
    human_decision: null,
    has_allocation: true,
    has_risk: true,
    has_execution: false,
    updated_at: new Date().toISOString(),
  },
  {
    id: "33333333-3333-3333-3333-333333333302",
    name: "Office renovation",
    status: "executing",
    risk_level: "low",
    approval_status: "approved",
    execution_status: "invoking_tool",
    missing_information: [],
    unresolved_assignments: [],
    policy_evidence: ["FAC-010 facilities spend"],
    source_refs: [{ type: "policy", id: "p2", label: "Facilities Policy" }],
    recommendations: ["Send PO draft to Contoso"],
    human_decision: "Approved by manager",
    has_allocation: true,
    has_risk: true,
    has_execution: true,
    updated_at: new Date().toISOString(),
  },
  {
    id: "33333333-3333-3333-3333-333333333303",
    name: "Software renewal",
    status: "blocked",
    risk_level: "high",
    approval_status: "invalidated",
    execution_status: null,
    missing_information: ["Renewal quote attachment"],
    unresolved_assignments: ["Compliance reviewer"],
    policy_evidence: ["SEC-200 vendor risk"],
    source_refs: [{ type: "document", id: "d3", label: "Vendor questionnaire" }],
    recommendations: ["Re-run risk analysis after quote upload"],
    human_decision: null,
    has_allocation: true,
    has_risk: true,
    has_execution: false,
    updated_at: new Date().toISOString(),
  },
];

const PROCESS_RUNS: ProcessRun[] = [
  {
    id: "55555555-5555-5555-5555-555555555501",
    organization_id: ORG_ID,
    process_id: "33333333-3333-3333-3333-333333333302",
    process_version_id: null,
    status: "executing",
    initiated_by_user_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    correlation_id: "corr-run-office",
    created_at: new Date(Date.now() - 1000 * 60 * 18).toISOString(),
    updated_at: new Date().toISOString(),
    dry_run: false,
    current_step_index: 2,
    pause_reason: null,
  },
  {
    id: "55555555-5555-5555-5555-555555555502",
    organization_id: ORG_ID,
    process_id: "33333333-3333-3333-3333-333333333303",
    process_version_id: null,
    status: "blocked",
    initiated_by_user_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    correlation_id: "corr-run-software",
    created_at: new Date(Date.now() - 1000 * 60 * 60).toISOString(),
    updated_at: new Date().toISOString(),
    dry_run: false,
    current_step_index: 0,
    pause_reason: "Missing renewal quote attachment",
  },
];

const AUDIT_EVENTS: AuditEvent[] = [
  {
    id: "66666666-6666-6666-6666-666666666601",
    organization_id: ORG_ID,
    actor_user_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    action: "approval.decided",
    resource_type: "approval",
    resource_id: "44444444-4444-4444-4444-444444444401",
    correlation_id: "corr-approval-1",
    payload: { result: "success", decision: "approved", process_name: "Laptop procurement" },
    created_at: new Date(Date.now() - 1000 * 60 * 12).toISOString(),
    result: "success",
  },
  {
    id: "66666666-6666-6666-6666-666666666602",
    organization_id: ORG_ID,
    actor_user_id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    action: "document.created",
    resource_type: "document",
    resource_id: "77777777-7777-7777-7777-777777777701",
    correlation_id: "corr-doc-1",
    payload: { result: "success", title: "Uploaded RFQ notes" },
    created_at: new Date(Date.now() - 1000 * 60 * 45).toISOString(),
    result: "success",
  },
  {
    id: "66666666-6666-6666-6666-666666666603",
    organization_id: ORG_ID,
    actor_user_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    action: "process_run.created",
    resource_type: "process_run",
    resource_id: "55555555-5555-5555-5555-555555555501",
    correlation_id: "corr-run-office",
    payload: { result: "success", process_name: "Office renovation" },
    created_at: new Date(Date.now() - 1000 * 60 * 18).toISOString(),
    result: "success",
  },
  {
    id: "66666666-6666-6666-6666-666666666604",
    organization_id: ORG_ID,
    actor_user_id: null,
    action: "workflow.audit_checkpoint",
    resource_type: "workflow",
    resource_id: "55555555-5555-5555-5555-555555555502",
    correlation_id: "corr-run-software",
    payload: { result: "blocked", reason: "policy hold" },
    created_at: new Date(Date.now() - 1000 * 60 * 8).toISOString(),
    result: "blocked",
  },
];

const APPROVALS: ApprovalSummary[] = [
  {
    id: "44444444-4444-4444-4444-444444444401",
    process_id: "33333333-3333-3333-3333-333333333301",
    process_name: "Laptop procurement",
    status: "pending",
    risk_level: "medium",
    risk_decision: "APPROVAL_REQUIRED",
    required_roles: ["manager"],
    snapshot_hash: "snap-abc",
    plan_snapshot_hash: "plan-hash-1",
    risk_snapshot_hash: "risk-hash-1",
    policy_evidence: ["PROC-001 §2 dual quotes", "FIN-001 §1 manager threshold"],
    source_refs: [{ type: "policy", id: "p1", label: "Procurement Approval Policy" }],
    decision_note: null,
    risk_summary:
      "Deterministic decision: APPROVAL_REQUIRED — spend above manager threshold; quotations incomplete.",
    risk_items: [
      {
        id: "risk_spend_manager",
        category: "financial",
        severity: "medium",
        description: "Spending amount 2,500.00 requires manager approval.",
        blocking: false,
        required_remediation: "Obtain manager approval against frozen snapshot.",
        required_approver: "manager",
        policy_code: "FIN-001",
      },
      {
        id: "risk_quotes_missing",
        category: "procurement",
        severity: "high",
        description: "Required quotation count is 2; found 1.",
        blocking: false,
        required_remediation: "Collect additional vendor quotations before proceeding.",
        required_approver: "procurement",
        policy_code: "PROC-001",
      },
    ],
    blocking_explanation: null,
    approval_history: [
      { at: new Date(Date.now() - 1000 * 60 * 75).toISOString(), action: "package_created", actor: "system", note: "Bound to plan+risk hashes" },
    ],
    override_required: false,
    created_at: new Date(Date.now() - 1000 * 60 * 75).toISOString(), // ~1 hour 15m ago
    updated_at: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
  },
  {
    id: "44444444-4444-4444-4444-444444444402",
    process_id: "33333333-3333-3333-3333-333333333302",
    process_name: "Unapproved vendor purchase",
    status: "pending",
    risk_level: "critical",
    risk_decision: "BLOCKED",
    required_roles: ["owner", "compliance"],
    snapshot_hash: "snap-block",
    plan_snapshot_hash: "plan-hash-2",
    risk_snapshot_hash: "risk-hash-2",
    policy_evidence: ["PROC-001 §3 approved suppliers"],
    source_refs: [{ type: "policy", id: "p1", label: "Procurement Approval Policy" }],
    decision_note: null,
    risk_summary: "Deterministic decision: BLOCKED — unapproved supplier cannot be used.",
    risk_items: [
      {
        id: "risk_supplier_x",
        category: "vendor",
        severity: "critical",
        description: "Supplier Contoso is not approved/active for use.",
        blocking: true,
        required_remediation: "Replace with an approved supplier or complete supplier approval.",
        required_approver: "compliance",
        policy_code: "PROC-001",
      },
    ],
    blocking_explanation:
      "Blocked actions cannot proceed without an audited override workflow. Gemini cannot approve this action.",
    approval_history: [
      { at: new Date(Date.now() - 1000 * 60 * 60 * 5).toISOString(), action: "blocked", actor: "agent_3", note: "Awaiting override" },
    ],
    override_required: true,
    created_at: new Date(Date.now() - 1000 * 60 * 60 * 5).toISOString(), // 5 hours ago
    updated_at: new Date(Date.now() - 1000 * 60 * 60 * 4).toISOString(),
  },
  {
    id: "44444444-4444-4444-4444-444444444403",
    process_id: "33333333-3333-3333-3333-333333333303",
    process_name: "Cloud infrastructure capacity upgrade",
    status: "approved",
    risk_level: "low",
    risk_decision: "CLEAR",
    required_roles: ["devops_lead"],
    snapshot_hash: "snap-infra",
    plan_snapshot_hash: "plan-hash-3",
    risk_snapshot_hash: "risk-hash-3",
    policy_evidence: ["INFRA-002 §1 capacity scaling within monthly budget"],
    source_refs: [{ type: "policy", id: "p2", label: "Infrastructure Scaling Policy" }],
    decision_note: "Approved per Q3 budget allocation",
    risk_summary: "Deterministic decision: CLEAR — standard capacity scaling within budget limits.",
    risk_items: [],
    blocking_explanation: null,
    approval_history: [
      { at: new Date(Date.now() - 1000 * 60 * 60 * 26).toISOString(), action: "package_created", actor: "system", note: "Auto-analyzed" },
      { at: new Date(Date.now() - 1000 * 60 * 60 * 25).toISOString(), action: "approved", actor: "alex.owner@example.com", note: "Approved" },
    ],
    override_required: false,
    created_at: new Date(Date.now() - 1000 * 60 * 60 * 26).toISOString(), // Yesterday (~26 hours ago)
    updated_at: new Date(Date.now() - 1000 * 60 * 60 * 25).toISOString(),
  },
  {
    id: "44444444-4444-4444-4444-444444444404",
    process_id: "33333333-3333-3333-3333-333333333304",
    process_name: "Off-cycle bonus payroll run",
    status: "rejected",
    risk_level: "high",
    risk_decision: "APPROVAL_REQUIRED",
    required_roles: ["finance_director"],
    snapshot_hash: "snap-payroll",
    plan_snapshot_hash: "plan-hash-4",
    risk_snapshot_hash: "risk-hash-4",
    policy_evidence: ["HR-004 §2 off-cycle compensation policy"],
    source_refs: [{ type: "policy", id: "p3", label: "Compensation & Payroll Policy" }],
    decision_note: "Rejected — missing written executive sign-off sheet.",
    risk_summary: "Deterministic decision: APPROVAL_REQUIRED — off-cycle payroll exceeds threshold without pre-cleared sign-off.",
    risk_items: [
      {
        id: "risk_payroll_signoff",
        category: "financial",
        severity: "high",
        description: "Off-cycle compensation exceeds standard threshold without pre-cleared sign-off.",
        blocking: false,
        required_remediation: "Attach signed executive compensation committee approval.",
        required_approver: "finance_director",
        policy_code: "HR-004",
      },
    ],
    blocking_explanation: null,
    approval_history: [
      { at: new Date(Date.now() - 1000 * 60 * 60 * 72).toISOString(), action: "package_created", actor: "system" },
      { at: new Date(Date.now() - 1000 * 60 * 60 * 70).toISOString(), action: "rejected", actor: "alex.owner@example.com", note: "Missing executive sheet" },
    ],
    override_required: false,
    created_at: new Date(Date.now() - 1000 * 60 * 60 * 72).toISOString(), // 3 days ago
    updated_at: new Date(Date.now() - 1000 * 60 * 60 * 70).toISOString(),
  },
];

const NOTIFICATIONS: Notification[] = [
  {
    id: "55555555-5555-5555-5555-555555555501",
    title: "Approval needed",
    body: "Laptop procurement awaits manager decision",
    status: "unread",
    created_at: new Date().toISOString(),
  },
  {
    id: "55555555-5555-5555-5555-555555555502",
    title: "Run paused",
    body: "Office renovation waiting on supplier response",
    status: "read",
    created_at: new Date().toISOString(),
  },
];

let orgProfile: OrganizationProfile = {
  id: ORG_ID,
  name: "Demo Organization",
  slug: "demo-organization",
  plan_code: "pro",
  status: "active",
  legal_name: "Demo Organization LLC",
  trading_name: "Demo Trading",
  industry: "Technology",
  country_code: "US",
  default_timezone: "UTC",
  default_currency: "USD",
  tax_id: "12-3456789",
  tax_information: { vat_registered: true },
  row_version: 1,
};

let employees: Employee[] = [
  {
    id: "66666666-6666-6666-6666-666666666601",
    organization_id: ORG_ID,
    full_name: "Alex Owner",
    email: "alex@demo.test",
    title: "Organization Owner",
    is_manager: true,
    status: "active",
    role_code: "owner",
    approval_authority_limit: 100000,
    approval_authority_currency: "USD",
  },
  {
    id: "66666666-6666-6666-6666-666666666602",
    organization_id: ORG_ID,
    full_name: "Sam Employee",
    email: "sam@demo.test",
    title: "Procurement Specialist",
    is_manager: false,
    status: "active",
    role_code: "employee",
  },
];

let departments: Department[] = [
  {
    id: "77777777-7777-7777-7777-777777777701",
    organization_id: ORG_ID,
    name: "Operations",
    code: "OPS",
    status: "active",
  },
];

let costCenters: CostCenter[] = [
  {
    id: "88888888-8888-8888-8888-888888888801",
    organization_id: ORG_ID,
    code: "CC-100",
    name: "Ops Cost Center",
    department_id: departments[0].id,
    status: "active",
  },
];

let budgets: Budget[] = [
  {
    id: "99999999-9999-9999-9999-999999999901",
    organization_id: ORG_ID,
    name: "FY26 Ops",
    fiscal_year: 2026,
    amount_total: 250000,
    currency_code: "USD",
    status: "active",
    department_id: departments[0].id,
    cost_center_id: costCenters[0].id,
  },
];

let suppliers: Supplier[] = [
  {
    id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaa01",
    organization_id: ORG_ID,
    name: "Northwind Supplies",
    code: "NW-1",
    status: "active",
    approval_status: "approved",
    country_code: "US",
  },
  {
    id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaa02",
    organization_id: ORG_ID,
    name: "Contoso Components",
    code: "CO-1",
    status: "active",
    approval_status: "pending",
    country_code: "US",
  },
];

let supplierContacts: SupplierContact[] = [
  {
    id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbb01",
    organization_id: ORG_ID,
    supplier_id: suppliers[0].id,
    full_name: "Pat Contact",
    email: "pat@northwind.test",
    is_primary: true,
    status: "active",
  },
];

let supplierProducts: SupplierProduct[] = [
  {
    id: "cccccccc-cccc-cccc-cccc-cccccccccc01",
    organization_id: ORG_ID,
    supplier_id: suppliers[0].id,
    name: "Laptop Pro 14",
    sku: "LP-14",
    unit_price: 1299,
    currency_code: "USD",
    status: "active",
  },
];

let policies: Policy[] = [
  {
    id: "dddddddd-dddd-dddd-dddd-dddddddddd01",
    organization_id: ORG_ID,
    code: "PROC-001",
    title: "Procurement Approval Policy",
    status: "active",
    category: "procurement",
    metadata: { owner_team: "finance" },
  },
];

let documents: Document[] = [
  {
    id: "eeeeeeee-eeee-eeee-eeee-eeeeeeeeee01",
    organization_id: ORG_ID,
    title: "Laptop RFQ notes",
    storage_path: `${ORG_ID}/laptop-rfq-notes.md`,
    status: "indexed",
    file_name: "laptop-rfq-notes.md",
    mime_type: "text/markdown",
    chunk_count: 2,
    embedding_model: "foundation-hash-embedding-v1",
    embedding_dimension: 1536,
    suspicious_flags: [],
    redacted: false,
    classification: "internal",
    access_scope: "organization",
  },
];

let documentChunks: Array<{
  document_id: string;
  content: string;
  page_number: number | null;
  section_heading: string | null;
}> = [
  {
    document_id: documents[0].id,
    content: "Laptop purchase requires dual quotes and manager approval.",
    page_number: 1,
    section_heading: "Requirements",
  },
];

function pageOf<T>(items: T[]) {
  return { items, meta: { total: items.length, limit: 50, offset: 0 } };
}

function parseCsv(content: string): Record<string, string>[] {
  const lines = content.trim().split(/\r?\n/);
  if (lines.length < 2) return [];
  const headers = lines[0].split(",").map((h) => h.trim().toLowerCase());
  return lines.slice(1).map((line) => {
    const cols = line.split(",");
    const row: Record<string, string> = {};
    headers.forEach((h, i) => {
      row[h] = (cols[i] ?? "").trim();
    });
    return row;
  });
}

function previewEmployees(csv: string): ImportPreview {
  const rows = parseCsv(csv);
  const errors: ImportPreview["errors"] = [];
  const duplicates: ImportPreview["duplicates"] = [];
  const valid_rows: Record<string, unknown>[] = [];
  const seen = new Set<string>();
  const existing = new Set(
    employees.filter((e) => e.status === "active").map((e) => e.email.toLowerCase()),
  );

  rows.forEach((row, idx) => {
    const rowNumber = idx + 2;
    if (!row.full_name) {
      errors.push({
        row_number: rowNumber,
        field: "full_name",
        code: "REQUIRED",
        message: "required",
      });
    }
    if (!row.email) {
      errors.push({
        row_number: rowNumber,
        field: "email",
        code: "REQUIRED",
        message: "required",
      });
    } else {
      const email = row.email.toLowerCase();
      if (seen.has(email) || existing.has(email)) {
        duplicates.push({
          row_number: rowNumber,
          field: "email",
          code: seen.has(email) ? "DUPLICATE_IN_FILE" : "DUPLICATE_ACTIVE",
          message: "Duplicate email",
        });
      } else {
        seen.add(email);
      }
    }
    if (
      !errors.some((e) => e.row_number === rowNumber) &&
      !duplicates.some((d) => d.row_number === rowNumber)
    ) {
      valid_rows.push(row);
    }
  });

  return {
    total_rows: rows.length,
    valid_count: valid_rows.length,
    error_count: errors.length,
    duplicate_count: duplicates.length,
    valid_rows,
    errors,
    duplicates,
  };
}

function previewSuppliers(csv: string): ImportPreview {
  const rows = parseCsv(csv);
  const errors: ImportPreview["errors"] = [];
  const duplicates: ImportPreview["duplicates"] = [];
  const valid_rows: Record<string, unknown>[] = [];
  const seen = new Set<string>();
  const existing = new Set(
    suppliers.filter((s) => s.status === "active").map((s) => s.name.toLowerCase()),
  );
  rows.forEach((row, idx) => {
    const rowNumber = idx + 2;
    if (!row.name) {
      errors.push({
        row_number: rowNumber,
        field: "name",
        code: "REQUIRED",
        message: "required",
      });
    } else {
      const key = row.name.toLowerCase();
      if (seen.has(key) || existing.has(key)) {
        duplicates.push({
          row_number: rowNumber,
          field: "name",
          code: seen.has(key) ? "DUPLICATE_IN_FILE" : "DUPLICATE_ACTIVE",
          message: "Duplicate name",
        });
      } else seen.add(key);
    }
    if (
      !errors.some((e) => e.row_number === rowNumber) &&
      !duplicates.some((d) => d.row_number === rowNumber)
    ) {
      valid_rows.push(row);
    }
  });
  return {
    total_rows: rows.length,
    valid_count: valid_rows.length,
    error_count: errors.length,
    duplicate_count: duplicates.length,
    valid_rows,
    errors,
    duplicates,
  };
}

type MockEntitlement = {
  feature_code: string;
  numeric_limit?: number | null;
  boolean_value?: boolean | null;
  text_value?: string | null;
};

const MOCK_BILLING_PLANS = [
  {
    plan_code: "pro" as const,
    display_name: "Pro",
    description: "One company instance with standard BPM capabilities.",
    sort_order: 1,
    highlights: [
      "One company instance",
      "Basic process discovery",
      "Standard email integration",
      "Limited workflow runs",
    ],
    entitlements: [
      { feature_code: "organization.max_users", numeric_limit: 25 },
      { feature_code: "process.monthly_runs", numeric_limit: 100 },
      { feature_code: "integrations.email_enabled", boolean_value: true },
      { feature_code: "security.sso_enabled", boolean_value: false },
      { feature_code: "analytics.advanced_enabled", boolean_value: false },
    ] satisfies MockEntitlement[],
  },
  {
    plan_code: "enterprise" as const,
    display_name: "Enterprise",
    description: "Multi-org scale with SSO, SCIM, and advanced workflows.",
    sort_order: 2,
    highlights: ["SSO and SAML", "SCIM", "Advanced audit exports", "Priority support"],
    entitlements: [
      { feature_code: "organization.max_users", numeric_limit: 500 },
      { feature_code: "process.monthly_runs", numeric_limit: 2000 },
      { feature_code: "integrations.email_enabled", boolean_value: true },
      { feature_code: "security.sso_enabled", boolean_value: true },
      { feature_code: "analytics.advanced_enabled", boolean_value: true },
    ] satisfies MockEntitlement[],
  },
  {
    plan_code: "pro_max" as const,
    display_name: "Pro Max",
    description: "Highest limits, dedicated capacity, and premium support.",
    sort_order: 3,
    highlights: ["Dedicated workers", "Advanced analytics", "Premium support"],
    entitlements: [
      { feature_code: "organization.max_users", numeric_limit: 5000 },
      { feature_code: "process.monthly_runs", numeric_limit: 20000 },
      { feature_code: "integrations.email_enabled", boolean_value: true },
      { feature_code: "security.sso_enabled", boolean_value: true },
      { feature_code: "workers.dedicated_capacity", boolean_value: true },
      { feature_code: "support.premium", boolean_value: true },
      { feature_code: "analytics.advanced_enabled", boolean_value: true },
    ] satisfies MockEntitlement[],
  },
];

function mockSubscriptionSnapshot(planCode: Organization["plan_code"], orgId: string) {
  const plan = MOCK_BILLING_PLANS.find((p) => p.plan_code === planCode) ?? MOCK_BILLING_PLANS[0];
  const features: Record<string, boolean | null> = {};
  const limits: Record<string, number | null> = {};
  for (const row of plan.entitlements) {
    if (row.boolean_value != null) features[row.feature_code] = row.boolean_value;
    if (row.numeric_limit != null) limits[row.feature_code] = row.numeric_limit;
  }
  return {
    organization_id: orgId,
    plan_code: planCode,
    subscription: {
      id: "sub-mock-1",
      status: "active",
      plan_code: planCode,
      cancel_at_period_end: false,
    },
    entitlements: plan.entitlements,
    features,
    limits,
  };
}

export const mockApi = {
  async request<T>(path: string, init?: RequestInit): Promise<T> {
    await Promise.resolve();
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};

    if (path === "/healthz") {
      return { status: "ok", service: "intelligent-bpm", version: "0.1.0" } as T;
    }
    if (path === "/readyz") {
      return {
        ready: true,
        service: "intelligent-bpm",
        checks: [{ name: "mock", ready: true, detail: "mock mode" }],
      } as T;
    }
    if (path === "/auth/organizations") return ORGS as T;
    if (path === "/organizations" && method === "POST") {
      const newOrg: Organization = {
        id: "00000000-0000-0000-0000-000000000099",
        name: String(body.name || "Acme Corporation"),
        slug: String(body.name || "acme-corp").toLowerCase().replace(/[^a-z0-9]+/g, "-"),
        plan_code: (body.plan_code as Organization["plan_code"]) || "pro",
        status: "active",
        membership_role: "owner",
      };
      ORGS.push(newOrg);
      return newOrg as T;
    }
    if (path === "/boom") {
      throw new ApiError("Simulated failure", {
        code: "INTERNAL_ERROR",
        status: 500,
        correlationId: "corr-mock-1",
      });
    }

    if (path.startsWith("/organizations/") && method === "GET") {
      return orgProfile as T;
    }
    if (path.startsWith("/organizations/") && method === "PATCH") {
      orgProfile = {
        ...orgProfile,
        ...body,
        tax_information:
          (body.tax_information as Record<string, unknown> | undefined) ??
          orgProfile.tax_information,
        row_version: (orgProfile.row_version ?? 1) + 1,
      };
      return orgProfile as T;
    }

    if (path.startsWith("/employees") && method === "GET" && !path.includes("/deactivate")) {
      const url = new URL(path, "http://local");
      const q = url.searchParams.get("q")?.toLowerCase();
      const status = url.searchParams.get("status");
      let items = [...employees];
      if (q) {
        items = items.filter(
          (e) => e.full_name.toLowerCase().includes(q) || e.email.includes(q),
        );
      }
      if (status) items = items.filter((e) => e.status === status);
      return pageOf(items) as T;
    }
    if (path === "/employees" && method === "POST") {
      const email = String(body.email).toLowerCase();
      if (employees.some((e) => e.status === "active" && e.email === email)) {
        throw new ApiError("Duplicate active email", {
          code: "DUPLICATE_EMPLOYEE_EMAIL",
          status: 409,
        });
      }
      const created: Employee = {
        id: crypto.randomUUID(),
        organization_id: ORG_ID,
        full_name: String(body.full_name),
        email,
        title: (body.title as string | null) ?? null,
        is_manager: Boolean(body.is_manager),
        status: "active",
        role_code: (body.role_code as string | null) ?? null,
        approval_authority_limit: (body.approval_authority_limit as number | null) ?? null,
        approval_authority_currency: "USD",
      };
      employees = [...employees, created];
      return created as T;
    }
    if (path.match(/\/employees\/[^/]+\/deactivate$/) && method === "POST") {
      const id = path.split("/")[2];
      employees = employees.map((e) => (e.id === id ? { ...e, status: "inactive" } : e));
      const found = employees.find((e) => e.id === id);
      if (!found) throw new ApiError("Not found", { code: "NOT_FOUND", status: 404 });
      return found as T;
    }

    if (path.startsWith("/departments") && method === "GET") return pageOf(departments) as T;
    if (path === "/departments" && method === "POST") {
      const created: Department = {
        id: crypto.randomUUID(),
        organization_id: ORG_ID,
        name: String(body.name),
        code: (body.code as string | null) ?? null,
        status: "active",
      };
      departments = [...departments, created];
      return created as T;
    }

    if (path.startsWith("/cost-centers") && method === "GET") return pageOf(costCenters) as T;
    if (path === "/cost-centers" && method === "POST") {
      const created: CostCenter = {
        id: crypto.randomUUID(),
        organization_id: ORG_ID,
        code: String(body.code),
        name: String(body.name),
        department_id: (body.department_id as string | null) ?? null,
        status: "active",
      };
      costCenters = [...costCenters, created];
      return created as T;
    }

    if (path.startsWith("/budgets") && method === "GET") return pageOf(budgets) as T;
    if (path === "/budgets" && method === "POST") {
      const created: Budget = {
        id: crypto.randomUUID(),
        organization_id: ORG_ID,
        name: String(body.name),
        fiscal_year: Number(body.fiscal_year),
        amount_total: Number(body.amount_total),
        currency_code: String(body.currency_code ?? "USD"),
        status: "active",
        department_id: (body.department_id as string | null) ?? null,
        cost_center_id: (body.cost_center_id as string | null) ?? null,
      };
      budgets = [...budgets, created];
      return created as T;
    }

    if (path.startsWith("/suppliers") && method === "GET" && !path.includes("/deactivate")) {
      const url = new URL(path, "http://local");
      const status = url.searchParams.get("status");
      let items = [...suppliers];
      if (status) items = items.filter((s) => s.status === status);
      return pageOf(items) as T;
    }
    if (path === "/suppliers" && method === "POST") {
      const created: Supplier = {
        id: crypto.randomUUID(),
        organization_id: ORG_ID,
        name: String(body.name),
        code: (body.code as string | null) ?? null,
        status: "active",
        approval_status: (body.approval_status as Supplier["approval_status"]) ?? "pending",
      };
      suppliers = [...suppliers, created];
      return created as T;
    }
    if (path.match(/\/suppliers\/[^/]+\/deactivate$/) && method === "POST") {
      const id = path.split("/")[2];
      suppliers = suppliers.map((s) => (s.id === id ? { ...s, status: "inactive" } : s));
      const found = suppliers.find((s) => s.id === id);
      if (!found) throw new ApiError("Not found", { code: "NOT_FOUND", status: 404 });
      return found as T;
    }
    if (path.match(/^\/suppliers\/[^/]+$/) && method === "PATCH") {
      const id = path.split("/")[2];
      suppliers = suppliers.map((s) => (s.id === id ? ({ ...s, ...body } as Supplier) : s));
      const found = suppliers.find((s) => s.id === id);
      if (!found) throw new ApiError("Not found", { code: "NOT_FOUND", status: 404 });
      return found as T;
    }

    if (path.startsWith("/supplier-contacts") && method === "GET") {
      return pageOf(supplierContacts) as T;
    }
    if (path === "/supplier-contacts" && method === "POST") {
      const email = body.email ? String(body.email).toLowerCase() : null;
      const supplierId = String(body.supplier_id);
      if (
        email &&
        !body.allow_duplicate_email &&
        supplierContacts.some(
          (c) =>
            c.supplier_id === supplierId &&
            c.status === "active" &&
            c.email?.toLowerCase() === email,
        )
      ) {
        throw new ApiError("Duplicate contact email", {
          code: "DUPLICATE_SUPPLIER_CONTACT_EMAIL",
          status: 409,
        });
      }
      const created: SupplierContact = {
        id: crypto.randomUUID(),
        organization_id: ORG_ID,
        supplier_id: supplierId,
        full_name: String(body.full_name),
        email,
        is_primary: Boolean(body.is_primary),
        status: "active",
        allow_duplicate_email: Boolean(body.allow_duplicate_email),
      };
      supplierContacts = [...supplierContacts, created];
      return created as T;
    }

    if (path.startsWith("/supplier-products") && method === "GET") {
      return pageOf(supplierProducts) as T;
    }
    if (path === "/supplier-products" && method === "POST") {
      const created: SupplierProduct = {
        id: crypto.randomUUID(),
        organization_id: ORG_ID,
        supplier_id: String(body.supplier_id),
        name: String(body.name),
        sku: (body.sku as string | null) ?? null,
        unit_price: (body.unit_price as number | null) ?? null,
        currency_code: String(body.currency_code ?? "USD"),
        status: "active",
      };
      supplierProducts = [...supplierProducts, created];
      return created as T;
    }

    if (path.startsWith("/policies") && method === "GET") return pageOf(policies) as T;
    if (path === "/policies" && method === "POST") {
      const created: Policy = {
        id: crypto.randomUUID(),
        organization_id: ORG_ID,
        code: String(body.code),
        title: String(body.title),
        status: "draft",
        category: (body.category as string | null) ?? null,
        metadata: (body.metadata as Record<string, unknown>) ?? {},
      };
      policies = [...policies, created];
      return created as T;
    }

    if (path.startsWith("/documents") && method === "GET" && path === "/documents") {
      return pageOf(documents) as T;
    }
    if (path === "/documents/ingest" && method === "POST") {
      const fileName = String(body.file_name ?? "upload.txt");
      const title = String(body.title ?? fileName);
      const contentB64 = String(body.content_base64 ?? "");
      let text = "";
      try {
        text = atob(contentB64);
      } catch {
        throw new ApiError("Invalid base64", { code: "VALIDATION_ERROR", status: 422 });
      }
      if (fileName.endsWith(".exe")) {
        throw new ApiError("Unsupported file type", { code: "VALIDATION_ERROR", status: 422 });
      }
      const hash = `hash-${text.length}-${fileName}`;
      if (documents.some((d) => d.content_hash === hash && d.status === "indexed")) {
        throw new ApiError("Duplicate file", { code: "DUPLICATE_DOCUMENT", status: 409 });
      }
      const flags: string[] = [];
      if (/ignore previous/i.test(text) || /grant.*tool/i.test(text)) {
        flags.push("ignore_system");
      }
      const created: Document = {
        id: crypto.randomUUID(),
        organization_id: ORG_ID,
        title,
        storage_path: `${ORG_ID}/${fileName}`,
        status: "indexed",
        file_name: fileName,
        mime_type: "text/plain",
        content_hash: hash,
        chunk_count: 1,
        embedding_model: "foundation-hash-embedding-v1",
        embedding_dimension: 1536,
        suspicious_flags: flags,
        redacted: /@/.test(text),
        classification: "internal",
        access_scope: "organization",
      };
      documents = [...documents, created];
      documentChunks = [
        ...documentChunks,
        {
          document_id: created.id,
          content: text.slice(0, 500),
          page_number: 1,
          section_heading: null,
        },
      ];
      return created as T;
    }
    if (path === "/documents/search" && method === "POST") {
      const query = String(body.query ?? "").toLowerCase();
      const hits = documentChunks
        .filter((c) => c.content.toLowerCase().includes(query.split(" ")[0] ?? query))
        .map((c) => {
          const doc = documents.find((d) => d.id === c.document_id)!;
          return {
            chunk_id: crypto.randomUUID(),
            document_id: doc.id,
            organization_id: ORG_ID,
            chunk_index: 0,
            content: c.content,
            score: 0.9,
            page_number: c.page_number,
            section_heading: c.section_heading,
            file_name: doc.file_name,
            title: doc.title,
            suspicious: (doc.suspicious_flags?.length ?? 0) > 0,
            citation: {
              document_id: doc.id,
              chunk_id: "chunk",
              file_name: doc.file_name ?? null,
              page_number: c.page_number,
              section_heading: c.section_heading,
              excerpt: c.content.slice(0, 200),
            },
          };
        });
      const response: DocumentSearchResponse = {
        hits,
        agent_context: body.include_agent_context
          ? `DOCUMENT DATA\n<<<UNTRUSTED_DOCUMENT_DATA>>>\n${hits.map((h) => h.content).join("\n")}\n<<<END_UNTRUSTED_DOCUMENT_DATA>>>`
          : null,
      };
      return response as T;
    }
    if (path.match(/\/documents\/[^/]+\/reprocess$/) && method === "POST") {
      const id = path.split("/")[2];
      const found = documents.find((d) => d.id === id);
      if (!found) throw new ApiError("Not found", { code: "NOT_FOUND", status: 404 });
      const updated = {
        ...found,
        version_number: (found.version_number ?? 1) + 1,
        status: "indexed",
      };
      documents = documents.map((d) => (d.id === id ? updated : d));
      return updated as T;
    }

    if (path === "/imports/employees/preview" && method === "POST") {
      return previewEmployees(String(body.csv_content ?? "")) as T;
    }
    if (path === "/imports/employees/commit" && method === "POST") {
      const preview = previewEmployees(String(body.csv_content ?? ""));
      if (preview.error_count || preview.duplicate_count) {
        throw new ApiError("Import validation failed", {
          code: "VALIDATION_ERROR",
          status: 422,
        });
      }
      const created_ids: string[] = [];
      for (const row of preview.valid_rows) {
        const created: Employee = {
          id: crypto.randomUUID(),
          organization_id: ORG_ID,
          full_name: String(row.full_name),
          email: String(row.email).toLowerCase(),
          title: (row.title as string | null) ?? null,
          is_manager: String(row.is_manager ?? "").toLowerCase() === "true",
          status: "active",
          role_code: (row.role_code as string | null) ?? null,
        };
        employees = [...employees, created];
        created_ids.push(created.id);
      }
      return { created_ids, created_count: created_ids.length } satisfies ImportCommit as T;
    }
    if (path === "/imports/suppliers/preview" && method === "POST") {
      return previewSuppliers(String(body.csv_content ?? "")) as T;
    }
    if (path === "/imports/suppliers/commit" && method === "POST") {
      const preview = previewSuppliers(String(body.csv_content ?? ""));
      if (preview.error_count || preview.duplicate_count) {
        throw new ApiError("Import validation failed", {
          code: "VALIDATION_ERROR",
          status: 422,
        });
      }
      const created_ids: string[] = [];
      for (const row of preview.valid_rows) {
        const created: Supplier = {
          id: crypto.randomUUID(),
          organization_id: ORG_ID,
          name: String(row.name),
          code: (row.code as string | null) ?? null,
          status: "active",
          approval_status:
            (row.approval_status as Supplier["approval_status"]) ?? "pending",
        };
        suppliers = [...suppliers, created];
        created_ids.push(created.id);
      }
      return { created_ids, created_count: created_ids.length } satisfies ImportCommit as T;
    }

    if (path === "/processes" && method === "POST") {
      const newProc: ProcessSummary = {
        id: "00000000-0000-0000-0000-000000000099",
        name: String(body.name || "New Process"),
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
        has_allocation: false,
        has_risk: false,
        has_execution: false,
        updated_at: new Date().toISOString(),
      };
      PROCESSES.push(newProc);
      return newProc as T;
    }
    if (path === "/processes/summaries") return PROCESSES as T;
    if (path.startsWith("/processes/summaries/")) {
      const id = path.split("/").pop();
      const found = PROCESSES.find((p) => p.id === id);
      if (!found) {
        throw new ApiError("Process not found", { code: "NOT_FOUND", status: 404 });
      }
      return found as T;
    }
    if (path.includes("/chat") && method === "POST") {
      return {
        id: "msg-1",
        role: "assistant",
        content: "I am Agent 1 (Process Discovery). I have analyzed your requirements.",
        clarifying_questions: [],
        intent: { goal: String(body.message || "") },
      } as T;
    }
    if (path.includes("/chat") && method === "GET") {
      return { session_id: "sess-1", messages: [] } as T;
    }
    if (path.includes("/draft-plan") && method === "POST") {
      return {
        version_id: "ver-1",
        version_number: 1,
        status: "draft",
        plan: { steps: [] },
      } as T;
    }
    if (path.includes("/plan") && method === "POST") {
      return {
        version_id: "ver-1",
        version_number: 1,
        status: "draft",
        plan: { steps: [] },
      } as T;
    }
    if (path.includes("/versions/") && path.endsWith("/confirm") && method === "POST") {
      return {
        version_id: "ver-1",
        version_number: 1,
        status: "confirmed",
        plan: { steps: [] },
      } as T;
    }
    if (path.includes("/analyze-risk") && method === "POST") {
      return { decision: "CLEAR", risk_items: [] } as T;
    }
    if (path.endsWith("/approvals") && method === "POST") {
      return { id: "appr-1", status: "pending" } as T;
    }
    if (path.endsWith("/complete") && method === "POST") {
      const id = path.split("/")[2];
      const found = PROCESSES.find((p) => p.id === id);
      if (!found) {
        throw new ApiError("Process not found", { code: "NOT_FOUND", status: 404 });
      }
      if (["completed", "cancelled"].includes(found.status)) {
        throw new ApiError(`Process is already ${found.status}`, {
          code: "PROCESS_ALREADY_TERMINAL",
          status: 400,
        });
      }
      found.status = "completed";
      found.execution_status = "completed";
      found.human_decision = found.human_decision || "Marked complete";
      found.updated_at = new Date().toISOString();
      const run = PROCESS_RUNS.find((r) => r.process_id === id);
      if (run && !["completed", "cancelled", "failed"].includes(run.status)) {
        run.status = "completed";
        run.updated_at = new Date().toISOString();
      }
      return { ...found } as T;
    }
    if (path === "/approvals/summaries") return APPROVALS as T;
    if (path === "/notifications") return NOTIFICATIONS as T;

    if (path === "/billing/plans" && method === "GET") {
      return { plans: MOCK_BILLING_PLANS } as T;
    }
    if (path === "/billing/subscription" && method === "GET") {
      return mockSubscriptionSnapshot(ORGS[0].plan_code, ORGS[0].id) as T;
    }
    if (path === "/billing/usage" && method === "GET") {
      return {
        organization_id: ORGS[0].id,
        period_usage: { "process.monthly_runs": 3 },
        limits: { "process.monthly_runs": ORGS[0].plan_code === "pro" ? 100 : 2000 },
      } as T;
    }
    if (path === "/billing/subscription/upgrade" && method === "POST") {
      const plan = String(body.plan_code) as Organization["plan_code"];
      ORGS[0].plan_code = plan;
      return mockSubscriptionSnapshot(plan, ORGS[0].id) as T;
    }
    if (path === "/billing/subscription/downgrade" && method === "POST") {
      const plan = String(body.plan_code) as Organization["plan_code"];
      ORGS[0].plan_code = plan;
      return mockSubscriptionSnapshot(plan, ORGS[0].id) as T;
    }
    if (path === "/billing/subscription/cancel" && method === "POST") {
      const snap = mockSubscriptionSnapshot(ORGS[0].plan_code, ORGS[0].id);
      snap.subscription = {
        ...snap.subscription!,
        cancel_at_period_end: true,
      };
      return snap as T;
    }

    if (path.startsWith("/audit-events") && method === "GET") {
      const url = new URL(path, "http://mock.local");
      const action = url.searchParams.get("action")?.toLowerCase() ?? "";
      const limit = Number(url.searchParams.get("limit") ?? "50");
      const offset = Number(url.searchParams.get("offset") ?? "0");
      let items = [...AUDIT_EVENTS].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      );
      if (action) items = items.filter((e) => e.action.toLowerCase().includes(action));
      const total = items.length;
      return {
        items: items.slice(offset, offset + limit),
        meta: { total, limit, offset },
      } as T;
    }

    if (path.startsWith("/process-runs") && method === "GET" && !path.includes("/events")) {
      const url = new URL(path, "http://mock.local");
      const limit = Number(url.searchParams.get("limit") ?? "50");
      const offset = Number(url.searchParams.get("offset") ?? "0");
      const items = [...PROCESS_RUNS];
      return {
        items: items.slice(offset, offset + limit),
        meta: { total: items.length, limit, offset },
      } as T;
    }

    throw new ApiError(`Mock route not found: ${path}`, { code: "NOT_FOUND", status: 404 });
  },
  orgs: ORGS,
  processes: PROCESSES,
  approvals: APPROVALS,
  notifications: NOTIFICATIONS,
};
