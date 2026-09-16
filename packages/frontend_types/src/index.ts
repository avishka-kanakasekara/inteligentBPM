import { z } from "zod";

export const HealthResponseSchema = z.object({
  status: z.literal("ok"),
  service: z.string(),
  version: z.string(),
});
export type HealthResponse = z.infer<typeof HealthResponseSchema>;

export const ReadinessCheckSchema = z.object({
  name: z.string(),
  ready: z.boolean(),
  detail: z.string().nullable().optional(),
});
export type ReadinessCheck = z.infer<typeof ReadinessCheckSchema>;

export const ReadinessResponseSchema = z.object({
  ready: z.boolean(),
  service: z.string(),
  checks: z.array(ReadinessCheckSchema),
});
export type ReadinessResponse = z.infer<typeof ReadinessResponseSchema>;

export const ErrorBodySchema = z.object({
  code: z.string(),
  message: z.string(),
  details: z.unknown().optional(),
  correlation_id: z.string().nullable().optional(),
});
export const ErrorResponseSchema = z.object({
  error: ErrorBodySchema,
});
export type ErrorResponse = z.infer<typeof ErrorResponseSchema>;

export const OrgRoleSchema = z.enum([
  "owner",
  "admin",
  "manager",
  "employee",
  "compliance",
  "auditor",
]);
export type OrgRole = z.infer<typeof OrgRoleSchema>;

export const ProcessStatusSchema = z.enum([
  "draft",
  "discovering",
  "plan_ready",
  "allocating",
  "allocated",
  "analyzing_risk",
  "risk_complete",
  "awaiting_approval",
  "approved",
  "rejected",
  "executing",
  "paused",
  "blocked",
  "failed",
  "completed",
  "cancelled",
]);
export type ProcessStatus = z.infer<typeof ProcessStatusSchema>;

export const RiskLevelSchema = z.enum(["low", "medium", "high", "critical"]);
export type RiskLevel = z.infer<typeof RiskLevelSchema>;

export const ApprovalStatusSchema = z.enum([
  "pending",
  "approved",
  "rejected",
  "invalidated",
  "expired",
  "cancelled",
]);
export type ApprovalStatus = z.infer<typeof ApprovalStatusSchema>;

export const SourceRefSchema = z.object({
  // Keep in sync with backend PlanSourceReference / EvidenceReference types.
  type: z.enum([
    "document",
    "policy",
    "message",
    "tool",
    "user",
    "chunk",
    "plan",
    "allocation",
    "rule",
  ]),
  id: z.string(),
  label: z
    .string()
    .nullable()
    .optional()
    .transform((value) => value ?? ""),
});
export type SourceRef = z.infer<typeof SourceRefSchema>;

export const OrganizationSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  slug: z.string(),
  plan_code: z.enum(["pro", "enterprise", "pro_max"]),
  status: z.string(),
  membership_role: OrgRoleSchema,
});
export type Organization = z.infer<typeof OrganizationSchema>;

export const UserSchema = z.object({
  id: z.string().uuid(),
  email: z.string().email(),
  displayName: z.string(),
});
export type User = z.infer<typeof UserSchema>;

export const ProcessSummarySchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  status: ProcessStatusSchema,
  risk_level: RiskLevelSchema.nullable(),
  approval_status: ApprovalStatusSchema.nullable(),
  execution_status: z.string().nullable(),
  missing_information: z.array(z.string()),
  unresolved_assignments: z.array(z.string()),
  policy_evidence: z.array(z.string()),
  source_refs: z.array(SourceRefSchema),
  recommendations: z.array(z.string()),
  human_decision: z.string().nullable(),
  has_allocation: z.boolean().optional().default(false),
  has_risk: z.boolean().optional().default(false),
  has_execution: z.boolean().optional().default(false),
  updated_at: z.string(),
});
export type ProcessSummary = z.infer<typeof ProcessSummarySchema>;

export const ApprovalSummarySchema = z.object({
  id: z.string().uuid(),
  process_id: z.string().uuid().nullish(),
  process_name: z.string().default(""),
  status: ApprovalStatusSchema,
  risk_level: RiskLevelSchema.default("low"),
  risk_decision: z
    .enum(["CLEAR", "APPROVAL_REQUIRED", "BLOCKED", "INSUFFICIENT_INFORMATION"])
    .nullish(),
  required_roles: z.array(z.string()).default([]),
  snapshot_hash: z.string(),
  plan_snapshot_hash: z.string().nullish(),
  risk_snapshot_hash: z.string().nullish(),
  policy_evidence: z.array(z.string()).default([]),
  source_refs: z.array(SourceRefSchema).default([]),
  decision_note: z.string().nullable().optional(),
  risk_summary: z.string().nullish(),
  risk_items: z
    .array(
      z.object({
        id: z.string(),
        category: z.string(),
        severity: z.string(),
        description: z.string(),
        blocking: z.boolean(),
        required_remediation: z.string(),
        required_approver: z.string().nullable().optional(),
        policy_code: z.string().nullish(),
      }),
    )
    .nullish(),
  blocking_explanation: z.string().nullable().optional(),
  approval_history: z
    .array(
      z.object({
        at: z.string(),
        action: z.string(),
        actor: z.string().optional(),
        note: z.string().optional(),
      }),
    )
    .nullish(),
  override_required: z.boolean().optional(),
});
export type ApprovalSummary = z.infer<typeof ApprovalSummarySchema>;

export const RiskResultSchema = z.object({
  process_id: z.string().uuid(),
  decision: z.enum(["CLEAR", "APPROVAL_REQUIRED", "BLOCKED", "INSUFFICIENT_INFORMATION"]),
  overall_status: z.string(),
  risk_items: z.array(z.record(z.string(), z.unknown())),
  blocking_issues: z.array(z.record(z.string(), z.unknown())),
  required_approvals: z.array(z.record(z.string(), z.unknown())),
  policy_evidence: z.array(z.record(z.string(), z.unknown())),
  reasoning_summary: z.string(),
  valid: z.boolean(),
  invalidated_reason: z.string().nullable().optional(),
  plan_snapshot_hash: z.string(),
  risk_snapshot_hash: z.string(),
});
export type RiskResult = z.infer<typeof RiskResultSchema>;

export const NotificationSchema = z.object({
  id: z.string(),
  title: z.string(),
  body: z.string(),
  body_preview: z.string().optional(),
  summary: z.string().optional(),
  status: z.enum(["unread", "read"]),
  created_at: z.string(),
  delivery_status: z.string().optional(),
  to: z.array(z.string()).optional(),
  display_name: z.string().nullable().optional(),
  email_status: z.string().nullable().optional(),
  process_id: z.string().nullable().optional(),
  process_name: z.string().nullable().optional(),
  mock: z.boolean().optional(),
  provider: z.string().nullable().optional(),
});
export type Notification = z.infer<typeof NotificationSchema>;

export const CalendarEventSchema = z.object({
  id: z.string(),
  title: z.string(),
  description: z.string().optional().default(""),
  description_preview: z.string().optional(),
  summary: z.string().optional(),
  start_at: z.string(),
  end_at: z.string().optional().default(""),
  attendees: z.array(z.string()).optional().default([]),
  status: z.string().optional().default("confirmed"),
  invites_sent: z.array(z.unknown()).optional().default([]),
  process_id: z.string().nullable().optional(),
  process_name: z.string().nullable().optional(),
  mock: z.boolean().optional(),
  provider: z.string().nullable().optional(),
  created_at: z.string().optional(),
});
export type CalendarEvent = z.infer<typeof CalendarEventSchema>;

export const TaskItemSchema = z.object({
  id: z.string(),
  title: z.string(),
  description: z.string().optional().default(""),
  description_preview: z.string().optional(),
  summary: z.string().optional(),
  assignee_id: z.string().nullable().optional(),
  assignee_name: z.string().nullable().optional(),
  to: z.array(z.string()).optional().default([]),
  due_at: z.string().nullable().optional(),
  status: z.string().optional().default("open"),
  email_status: z.string().nullable().optional(),
  process_id: z.string().nullable().optional(),
  process_name: z.string().nullable().optional(),
  mock: z.boolean().optional(),
  provider: z.string().nullable().optional(),
  created_at: z.string().optional(),
});
export type TaskItem = z.infer<typeof TaskItemSchema>;

export const GeneratedDocumentSchema = z.object({
  id: z.string(),
  title: z.string(),
  doc_type: z.string().optional().default("memo"),
  doc_type_label: z.string().optional(),
  content: z.string().optional().default(""),
  content_preview: z.string().optional().default(""),
  summary: z.string().optional(),
  word_count: z.number().optional(),
  byte_size: z.number().optional().default(0),
  status: z.string().optional().default("generated"),
  process_id: z.string().nullable().optional(),
  process_name: z.string().nullable().optional(),
  mock: z.boolean().optional(),
  provider: z.string().nullable().optional(),
  created_at: z.string().optional(),
});
export type GeneratedDocument = z.infer<typeof GeneratedDocumentSchema>;

export const EmailMessageSchema = z.object({
  id: z.string(),
  to: z.array(z.string()).optional().default([]),
  subject: z.string(),
  body: z.string().optional().default(""),
  body_preview: z.string().optional(),
  summary: z.string().optional(),
  status: z.string().optional(),
  provider: z.string().nullable().optional(),
  provider_message_id: z.string().nullable().optional(),
  thread_id: z.string().nullable().optional(),
  mock: z.boolean().optional(),
  process_id: z.string().nullable().optional(),
  process_name: z.string().nullable().optional(),
  created_at: z.string().optional(),
});
export type EmailMessage = z.infer<typeof EmailMessageSchema>;

export const PageMetaSchema = z.object({
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
});
export type PageMeta = z.infer<typeof PageMetaSchema>;

export const PageSchema = <T extends z.ZodTypeAny>(item: T) =>
  z.object({
    items: z.array(item),
    meta: PageMetaSchema,
  });

export const OrganizationProfileSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  slug: z.string(),
  plan_code: z.enum(["pro", "enterprise", "pro_max"]),
  status: z.string(),
  legal_name: z.string().nullable().optional(),
  trading_name: z.string().nullable().optional(),
  industry: z.string().nullable().optional(),
  country_code: z.string().nullable().optional(),
  tax_id: z.string().nullable().optional(),
  tax_registration: z.string().nullable().optional(),
  tax_country_code: z.string().nullable().optional(),
  default_timezone: z.string().optional(),
  default_currency: z.string().optional(),
  tax_information: z.record(z.unknown()).optional(),
  row_version: z.number().optional(),
});
export type OrganizationProfile = z.infer<typeof OrganizationProfileSchema>;

export const EmployeeSchema = z.object({
  id: z.string().uuid(),
  organization_id: z.string().uuid(),
  full_name: z.string(),
  email: z.string().email(),
  title: z.string().nullable().optional(),
  department_id: z.string().uuid().nullable().optional(),
  is_manager: z.boolean(),
  status: z.string(),
  employee_code: z.string().nullable().optional(),
  role_code: z.string().nullable().optional(),
  approval_authority_limit: z.number().nullable().optional(),
  approval_authority_currency: z.string().optional(),
  created_at: z.string().optional(),
  updated_at: z.string().optional(),
});
export type Employee = z.infer<typeof EmployeeSchema>;

export const DepartmentSchema = z.object({
  id: z.string().uuid(),
  organization_id: z.string().uuid(),
  name: z.string(),
  code: z.string().nullable().optional(),
  status: z.string(),
  parent_department_id: z.string().uuid().nullable().optional(),
  manager_employee_id: z.string().uuid().nullable().optional(),
});
export type Department = z.infer<typeof DepartmentSchema>;

export const CostCenterSchema = z.object({
  id: z.string().uuid(),
  organization_id: z.string().uuid(),
  code: z.string(),
  name: z.string(),
  department_id: z.string().uuid().nullable().optional(),
  status: z.string(),
});
export type CostCenter = z.infer<typeof CostCenterSchema>;

export const SupplierSchema = z.object({
  id: z.string().uuid(),
  organization_id: z.string().uuid(),
  name: z.string(),
  code: z.string().nullable().optional(),
  status: z.string(),
  approval_status: z.enum(["pending", "approved", "rejected", "suspended"]),
  website: z.string().nullable().optional(),
  country_code: z.string().nullable().optional(),
});
export type Supplier = z.infer<typeof SupplierSchema>;

export const SupplierContactSchema = z.object({
  id: z.string().uuid(),
  organization_id: z.string().uuid(),
  supplier_id: z.string().uuid(),
  full_name: z.string(),
  email: z.string().nullable().optional(),
  is_primary: z.boolean(),
  status: z.string(),
  allow_duplicate_email: z.boolean().optional(),
});
export type SupplierContact = z.infer<typeof SupplierContactSchema>;

export const SupplierProductSchema = z.object({
  id: z.string().uuid(),
  organization_id: z.string().uuid(),
  supplier_id: z.string().uuid(),
  name: z.string(),
  sku: z.string().nullable().optional(),
  unit_price: z.number().nullable().optional(),
  currency_code: z.string(),
  status: z.string(),
});
export type SupplierProduct = z.infer<typeof SupplierProductSchema>;

export const BudgetSchema = z.object({
  id: z.string().uuid(),
  organization_id: z.string().uuid(),
  name: z.string(),
  fiscal_year: z.number(),
  amount_total: z.number(),
  currency_code: z.string(),
  status: z.string(),
  department_id: z.string().uuid().nullable().optional(),
  cost_center_id: z.string().uuid().nullable().optional(),
});
export type Budget = z.infer<typeof BudgetSchema>;

export const PolicySchema = z.object({
  id: z.string().uuid(),
  organization_id: z.string().uuid(),
  code: z.string(),
  title: z.string(),
  status: z.string(),
  category: z.string().nullable().optional(),
  description: z.string().nullable().optional(),
  metadata: z.record(z.unknown()).optional(),
});
export type Policy = z.infer<typeof PolicySchema>;

export const ImportRowErrorSchema = z.object({
  row_number: z.number(),
  field: z.string().nullable(),
  code: z.string(),
  message: z.string(),
});
export type ImportRowError = z.infer<typeof ImportRowErrorSchema>;

export const ImportPreviewSchema = z.object({
  total_rows: z.number(),
  valid_count: z.number(),
  error_count: z.number(),
  duplicate_count: z.number(),
  valid_rows: z.array(z.record(z.unknown())),
  errors: z.array(ImportRowErrorSchema),
  duplicates: z.array(ImportRowErrorSchema),
});
export type ImportPreview = z.infer<typeof ImportPreviewSchema>;

export const ImportCommitSchema = z.object({
  created_ids: z.array(z.string()),
  created_count: z.number(),
});
export type ImportCommit = z.infer<typeof ImportCommitSchema>;

export const DocumentSchema = z.object({
  id: z.string().uuid(),
  organization_id: z.string().uuid(),
  title: z.string(),
  storage_path: z.string(),
  status: z.string(),
  uploaded_by_user_id: z.string().uuid().nullable().optional(),
  file_name: z.string().nullable().optional(),
  mime_type: z.string().nullable().optional(),
  byte_size: z.number().nullable().optional(),
  content_hash: z.string().nullable().optional(),
  version_number: z.number().optional(),
  source_type: z.string().optional(),
  classification: z.string().optional(),
  access_scope: z.string().optional(),
  chunk_count: z.number().optional(),
  embedding_model: z.string().nullable().optional(),
  embedding_dimension: z.number().nullable().optional(),
  failure_reason: z.string().nullable().optional(),
  suspicious_flags: z.array(z.string()).optional(),
  redacted: z.boolean().optional(),
  created_at: z.string().optional(),
  updated_at: z.string().optional(),
});
export type Document = z.infer<typeof DocumentSchema>;

export const DocumentCitationSchema = z.object({
  document_id: z.string(),
  chunk_id: z.string(),
  file_name: z.string().nullable(),
  page_number: z.number().nullable(),
  section_heading: z.string().nullable(),
  excerpt: z.string(),
});
export type DocumentCitation = z.infer<typeof DocumentCitationSchema>;

export const DocumentSearchHitSchema = z.object({
  chunk_id: z.string().uuid(),
  document_id: z.string().uuid(),
  organization_id: z.string().uuid(),
  chunk_index: z.number(),
  content: z.string(),
  score: z.number(),
  page_number: z.number().nullable().optional(),
  section_heading: z.string().nullable().optional(),
  file_name: z.string().nullable().optional(),
  title: z.string(),
  suspicious: z.boolean(),
  citation: DocumentCitationSchema,
});
export type DocumentSearchHit = z.infer<typeof DocumentSearchHitSchema>;

export const DocumentSearchResponseSchema = z.object({
  hits: z.array(DocumentSearchHitSchema),
  agent_context: z.string().nullable().optional(),
});
export type DocumentSearchResponse = z.infer<typeof DocumentSearchResponseSchema>;

export const PlanEntitlementRowSchema = z.object({
  feature_code: z.string(),
  numeric_limit: z.number().nullable().optional(),
  boolean_value: z.boolean().nullable().optional(),
  text_value: z.string().nullable().optional(),
});
export type PlanEntitlementRow = z.infer<typeof PlanEntitlementRowSchema>;

export const BillingPlanSchema = z.object({
  plan_code: z.enum(["pro", "enterprise", "pro_max"]),
  display_name: z.string(),
  description: z.string(),
  sort_order: z.number(),
  highlights: z.array(z.string()),
  entitlements: z.array(PlanEntitlementRowSchema),
});
export type BillingPlan = z.infer<typeof BillingPlanSchema>;

export const BillingPlansResponseSchema = z.object({
  plans: z.array(BillingPlanSchema),
});
export type BillingPlansResponse = z.infer<typeof BillingPlansResponseSchema>;

export const BillingSubscriptionSnapshotSchema = z.object({
  organization_id: z.string().uuid(),
  plan_code: z.enum(["pro", "enterprise", "pro_max"]),
  subscription: z
    .object({
      id: z.string(),
      status: z.string(),
      plan_code: z.string(),
      cancel_at_period_end: z.boolean().optional(),
    })
    .passthrough()
    .optional(),
  entitlements: z.array(PlanEntitlementRowSchema).optional(),
  features: z.record(z.string(), z.boolean().nullable()).optional(),
  limits: z.record(z.string(), z.number().nullable()).optional(),
});
export type BillingSubscriptionSnapshot = z.infer<typeof BillingSubscriptionSnapshotSchema>;

export const BillingUsageResponseSchema = z.object({
  organization_id: z.string().uuid(),
  period_usage: z.record(z.string(), z.number()),
  limits: z.record(z.string(), z.number().nullable()).optional(),
});
export type BillingUsageResponse = z.infer<typeof BillingUsageResponseSchema>;
