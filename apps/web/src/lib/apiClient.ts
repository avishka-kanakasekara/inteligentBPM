import {
  ApprovalSummarySchema,
  AuditEventSchema,
  BudgetSchema,
  BillingPlansResponseSchema,
  BillingSubscriptionSnapshotSchema,
  BillingUsageResponseSchema,
  CostCenterSchema,
  DepartmentSchema,
  DocumentSchema,
  DocumentSearchResponseSchema,
  EmployeeSchema,
  ErrorResponseSchema,
  HealthResponseSchema,
  ImportCommitSchema,
  ImportPreviewSchema,
  NotificationSchema,
  CalendarEventSchema,
  TaskItemSchema,
  GeneratedDocumentSchema,
  EmailMessageSchema,
  OrganizationProfileSchema,
  OrganizationSchema,
  PageSchema,
  PolicySchema,
  ProcessRunSchema,
  ProcessSummarySchema,
  ReadinessResponseSchema,
  SupplierContactSchema,
  SupplierProductSchema,
  SupplierSchema,
  type ApprovalSummary,
  type AuditEvent,
  type BillingPlansResponse,
  type BillingSubscriptionSnapshot,
  type BillingUsageResponse,
  type Budget,
  type CalendarEvent,
  type CostCenter,
  type Department,
  type Document,
  type DocumentSearchResponse,
  type Employee,
  type GeneratedDocument,
  type EmailMessage,
  type HealthResponse,
  type ImportCommit,
  type ImportPreview,
  type Notification,
  type Organization,
  type OrganizationProfile,
  type Policy,
  type ProcessRun,
  type ProcessSummary,
  type ReadinessResponse,
  type Supplier,
  type SupplierContact,
  type SupplierProduct,
  type TaskItem,
} from "@bpm/frontend-types";
import { sessionStore } from "./sessionStore";
import { mockApi } from "./mockApi";
import { isSupabaseAuthEnabled, refreshSession } from "./supabaseAuth";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly correlationId?: string | null;

  constructor(
    message: string,
    options: { code: string; status: number; correlationId?: string | null },
  ) {
    super(message);
    this.name = "ApiError";
    this.code = options.code;
    this.status = options.status;
    this.correlationId = options.correlationId;
  }
}

function useMock(): boolean {
  return (import.meta.env.VITE_USE_MOCK_API ?? "true") !== "false";
}

function getApiBaseUrl(): string {
  return import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/v1";
}

type RequestOptions = RequestInit & {
  organizationId?: string | null;
  /** Internal: skip refresh+retry after a prior 401. */
  _authRetry?: boolean;
};

let refreshInFlight: Promise<boolean> | null = null;

async function tryRefreshAccessToken(): Promise<boolean> {
  if (!isSupabaseAuthEnabled()) return false;
  const refreshToken = sessionStore.getRefreshToken();
  if (!refreshToken) return false;

  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const session = await refreshSession(refreshToken);
        sessionStore.setToken(session.accessToken);
        if (session.refreshToken) sessionStore.setRefreshToken(session.refreshToken);
        return true;
      } catch {
        return false;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

function forceLogoutToLogin(): void {
  sessionStore.clear();
  if (
    typeof window !== "undefined" &&
    !window.location.pathname.startsWith("/login") &&
    !window.location.pathname.startsWith("/signup")
  ) {
    window.location.assign("/login?logout=true");
  }
}

async function request<T>(
  path: string,
  parse: (data: unknown) => T,
  init?: RequestOptions,
): Promise<T> {
  if (useMock()) {
    return mockApi.request(path, init);
  }

  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (init?.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const token = sessionStore.getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const orgId = init?.organizationId ?? sessionStore.getOrganizationId();
  if (orgId) headers["X-Organization-Id"] = orgId;

  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers,
  });

  const correlationId = response.headers.get("X-Correlation-Id");
  const json: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    const parsedError = ErrorResponseSchema.safeParse(json);
    if (parsedError.success) {
      if (
        response.status === 401 &&
        parsedError.data.error.code === "AUTH_UNAUTHORIZED"
      ) {
        // Stale token on /auth/organizations used to be ignored — that left the UI stuck.
        if (!init?._authRetry) {
          const refreshed = await tryRefreshAccessToken();
          if (refreshed) {
            return request(path, parse, { ...init, _authRetry: true });
          }
        }
        forceLogoutToLogin();
      }
      throw new ApiError(parsedError.data.error.message, {
        code: parsedError.data.error.code,
        status: response.status,
        correlationId: parsedError.data.error.correlation_id ?? correlationId,
      });
    }
    throw new ApiError("Request failed", {
      code: "HTTP_ERROR",
      status: response.status,
      correlationId,
    });
  }

  return parse(json);
}

const EmployeePageSchema = PageSchema(EmployeeSchema);
const DepartmentPageSchema = PageSchema(DepartmentSchema);
const CostCenterPageSchema = PageSchema(CostCenterSchema);
const BudgetPageSchema = PageSchema(BudgetSchema);
const SupplierPageSchema = PageSchema(SupplierSchema);
const SupplierContactPageSchema = PageSchema(SupplierContactSchema);
const SupplierProductPageSchema = PageSchema(SupplierProductSchema);
const PolicyPageSchema = PageSchema(PolicySchema);
const DocumentPageSchema = PageSchema(DocumentSchema);

export const apiClient = {
  getHealth(): Promise<HealthResponse> {
    return request("/healthz", (data) => HealthResponseSchema.parse(data));
  },
  getReadiness(): Promise<ReadinessResponse> {
    return request("/readyz", (data) => ReadinessResponseSchema.parse(data));
  },
  listOrganizations(): Promise<Organization[]> {
    return request("/auth/organizations", (data) =>
      OrganizationSchema.array().parse(data),
    );
  },
  createOrganization(body: { name: string; plan_code?: string }): Promise<Organization> {
    return request(
      "/organizations",
      (data) => {
        const payload =
          typeof data === "object" && data !== null
            ? { membership_role: "owner", ...(data as Record<string, unknown>) }
            : data;
        return OrganizationSchema.parse(payload);
      },
      {
        method: "POST",
        body: JSON.stringify({ name: body.name, plan_code: body.plan_code || "pro" }),
      },
    );
  },
  getOrganizationProfile(orgId: string): Promise<OrganizationProfile> {
    return request(
      `/organizations/${orgId}`,
      (data) => OrganizationProfileSchema.parse(data),
      { organizationId: orgId },
    );
  },
  updateOrganizationProfile(
    orgId: string,
    body: Partial<OrganizationProfile>,
  ): Promise<OrganizationProfile> {
    return request(
      `/organizations/${orgId}`,
      (data) => OrganizationProfileSchema.parse(data),
      { method: "PATCH", body: JSON.stringify(body), organizationId: orgId },
    );
  },
  listEmployees(query = ""): Promise<{ items: Employee[]; meta: { total: number } }> {
    return request(`/employees${query}`, (data) => EmployeePageSchema.parse(data));
  },
  createEmployee(body: Record<string, unknown>): Promise<Employee> {
    return request("/employees", (data) => EmployeeSchema.parse(data), {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  deactivateEmployee(id: string): Promise<Employee> {
    return request(`/employees/${id}/deactivate`, (data) => EmployeeSchema.parse(data), {
      method: "POST",
    });
  },
  listDepartments(): Promise<{ items: Department[] }> {
    return request("/departments", (data) => DepartmentPageSchema.parse(data));
  },
  createDepartment(body: Record<string, unknown>): Promise<Department> {
    return request("/departments", (data) => DepartmentSchema.parse(data), {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  listCostCenters(): Promise<{ items: CostCenter[] }> {
    return request("/cost-centers", (data) => CostCenterPageSchema.parse(data));
  },
  createCostCenter(body: Record<string, unknown>): Promise<CostCenter> {
    return request("/cost-centers", (data) => CostCenterSchema.parse(data), {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  listBudgets(): Promise<{ items: Budget[] }> {
    return request("/budgets", (data) => BudgetPageSchema.parse(data));
  },
  createBudget(body: Record<string, unknown>): Promise<Budget> {
    return request("/budgets", (data) => BudgetSchema.parse(data), {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  listSuppliers(query = ""): Promise<{ items: Supplier[] }> {
    return request(`/suppliers${query}`, (data) => SupplierPageSchema.parse(data));
  },
  createSupplier(body: Record<string, unknown>): Promise<Supplier> {
    return request("/suppliers", (data) => SupplierSchema.parse(data), {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  updateSupplier(id: string, body: Record<string, unknown>): Promise<Supplier> {
    return request(`/suppliers/${id}`, (data) => SupplierSchema.parse(data), {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  },
  deactivateSupplier(id: string): Promise<Supplier> {
    return request(`/suppliers/${id}/deactivate`, (data) => SupplierSchema.parse(data), {
      method: "POST",
    });
  },
  listSupplierContacts(): Promise<{ items: SupplierContact[] }> {
    return request("/supplier-contacts", (data) => SupplierContactPageSchema.parse(data));
  },
  createSupplierContact(body: Record<string, unknown>): Promise<SupplierContact> {
    return request("/supplier-contacts", (data) => SupplierContactSchema.parse(data), {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  listSupplierProducts(): Promise<{ items: SupplierProduct[] }> {
    return request("/supplier-products", (data) => SupplierProductPageSchema.parse(data));
  },
  createSupplierProduct(body: Record<string, unknown>): Promise<SupplierProduct> {
    return request("/supplier-products", (data) => SupplierProductSchema.parse(data), {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  listPolicies(): Promise<{ items: Policy[] }> {
    return request("/policies", (data) => PolicyPageSchema.parse(data));
  },
  createPolicy(body: Record<string, unknown>): Promise<Policy> {
    return request("/policies", (data) => PolicySchema.parse(data), {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  listDocuments(query = ""): Promise<{ items: Document[] }> {
    return request(`/documents${query}`, (data) => DocumentPageSchema.parse(data));
  },
  ingestDocument(body: Record<string, unknown>): Promise<Document> {
    return request("/documents/ingest", (data) => DocumentSchema.parse(data), {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  reprocessDocument(id: string): Promise<Document> {
    return request(`/documents/${id}/reprocess`, (data) => DocumentSchema.parse(data), {
      method: "POST",
    });
  },
  searchDocuments(body: {
    query: string;
    mode?: string;
    include_agent_context?: boolean;
    similarity_threshold?: number;
  }): Promise<DocumentSearchResponse> {
    return request("/documents/search", (data) => DocumentSearchResponseSchema.parse(data), {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  previewEmployeeImport(csv_content: string): Promise<ImportPreview> {
    return request("/imports/employees/preview", (data) => ImportPreviewSchema.parse(data), {
      method: "POST",
      body: JSON.stringify({ csv_content }),
    });
  },
  commitEmployeeImport(csv_content: string): Promise<ImportCommit> {
    return request("/imports/employees/commit", (data) => ImportCommitSchema.parse(data), {
      method: "POST",
      body: JSON.stringify({ csv_content }),
    });
  },
  previewSupplierImport(csv_content: string): Promise<ImportPreview> {
    return request("/imports/suppliers/preview", (data) => ImportPreviewSchema.parse(data), {
      method: "POST",
      body: JSON.stringify({ csv_content }),
    });
  },
  commitSupplierImport(csv_content: string): Promise<ImportCommit> {
    return request("/imports/suppliers/commit", (data) => ImportCommitSchema.parse(data), {
      method: "POST",
      body: JSON.stringify({ csv_content }),
    });
  },
  listProcesses(): Promise<ProcessSummary[]> {
    return request("/processes/summaries", (data) =>
      ProcessSummarySchema.array().parse(data),
    );
  },
  getProcess(id: string): Promise<ProcessSummary> {
    return request(`/processes/summaries/${id}`, (data) =>
      ProcessSummarySchema.parse(data),
    );
  },
  createProcess(data: { name: string; description?: string }): Promise<ProcessSummary> {
    return request("/processes", (res) => ProcessSummarySchema.parse(res), {
      method: "POST",
      body: JSON.stringify(data),
    }).then(async (created) => {
      // Backend returns a full summary after create; refetch if older shape is returned.
      if (
        typeof created === "object" &&
        created !== null &&
        "unresolved_assignments" in created
      ) {
        return created;
      }
      const summary = await request(
        `/processes/summaries/${(created as ProcessSummary).id}`,
        (payload) => ProcessSummarySchema.parse(payload),
      );
      return summary;
    });
  },
  chatDiscovery(
    processId: string,
    message: string,
    documentIds?: string[],
  ): Promise<any> {
    return request(`/processes/${processId}/chat`, (res) => res, {
      method: "POST",
      body: JSON.stringify({ message, document_ids: documentIds }),
    });
  },
  getDiscoveryChat(processId: string): Promise<any> {
    return request(`/processes/${processId}/chat`, (res) => res);
  },
  draftPlan(
    processId: string,
    options?: { document_ids?: string[]; instructions?: string; revision_of_version_id?: string },
  ): Promise<any> {
    return request(`/processes/${processId}/draft-plan`, (res) => res, {
      method: "POST",
      body: JSON.stringify(options || {}),
    });
  },
  confirmPlan(processId: string, versionId: string): Promise<any> {
    return request(`/processes/${processId}/versions/${versionId}/confirm`, (res) => res, {
      method: "POST",
    });
  },
  allocateResources(processId: string, options?: { process_version_id?: string }): Promise<any> {
    return request(`/processes/${processId}/allocate`, (res) => res, {
      method: "POST",
      body: JSON.stringify({ process_id: processId, ...options }),
    });
  },
  getAllocation(processId: string): Promise<any> {
    return request(`/processes/${processId}/allocation`, (res) => res);
  },
  analyzeRisk(
    processId: string,
    options?: { process_version_id?: string; spending_amount?: number },
  ): Promise<any> {
    return request(`/processes/${processId}/analyze-risk`, (res) => res, {
      method: "POST",
      body: JSON.stringify(options || {}),
    });
  },
  getRisk(processId: string): Promise<any> {
    return request(`/processes/${processId}/risk`, (res) => res);
  },
  createApprovalPackage(processId: string): Promise<any> {
    return request(`/processes/${processId}/approvals`, (res) => res, {
      method: "POST",
    });
  },
  startExecution(
    processId: string,
    options?: {
      dry_run?: boolean;
      auto_run?: boolean;
      max_steps?: number;
      approval_id?: string;
      process_version_id?: string;
    },
  ): Promise<any> {
    return request(`/processes/${processId}/execute`, (res) => res, {
      method: "POST",
      body: JSON.stringify(options || {}),
    });
  },
  advanceExecution(processId: string, maxSteps = 10): Promise<any> {
    return request(
      `/processes/${processId}/execution/advance?max_steps=${maxSteps}`,
      (res) => res,
      { method: "POST" },
    );
  },
  resumeExecution(processId: string): Promise<any> {
    return request(`/processes/${processId}/execution/resume`, (res) => res, {
      method: "POST",
    });
  },
  pauseExecution(processId: string, reason?: string, runId?: string): Promise<any> {
    return request(`/processes/${processId}/execution/pause`, (res) => res, {
      method: "POST",
      body: JSON.stringify({ reason, run_id: runId }),
    });
  },
  cancelExecution(processId: string, reason?: string, runId?: string): Promise<any> {
    return request(`/processes/${processId}/execution/cancel`, (res) => res, {
      method: "POST",
      body: JSON.stringify({ reason, run_id: runId }),
    });
  },
  resetExecution(processId: string, runId?: string): Promise<any> {
    return request(`/processes/${processId}/execution/reset`, (res) => res, {
      method: "POST",
      body: JSON.stringify({ run_id: runId }),
    });
  },
  getExecutionReport(processId: string, runId?: string): Promise<any> {
    const q = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    return request(`/processes/${processId}/execution/report${q}`, (res) => res);
  },
  listTools(): Promise<any[]> {
    return request("/tools", (res) => res as any[]);
  },
  listQuotations(processId: string): Promise<{ items: any[] }> {
    return request(`/processes/${processId}/quotations`, (res) => res as { items: any[] });
  },
  compareQuotations(
    processId: string,
    quotationIds: string[],
    explain = true,
  ): Promise<any> {
    return request(`/processes/${processId}/quotations/compare`, (res) => res, {
      method: "POST",
      body: JSON.stringify({ quotation_ids: quotationIds, explain }),
    });
  },
  listPurchaseOrders(processId: string): Promise<{ items: any[] }> {
    return request(`/processes/${processId}/purchase-orders`, (res) => res as { items: any[] });
  },
  submitPurchaseOrder(
    purchaseOrderId: string,
    options: { process_id: string; idempotency_key: string; dry_run?: boolean },
  ): Promise<any> {
    return request(`/purchase-orders/${purchaseOrderId}/submit`, (res) => res, {
      method: "POST",
      body: JSON.stringify(options),
    });
  },
  getExecution(processId: string): Promise<any> {
    return request(`/processes/${processId}/execution`, (res) => res);
  },
  completeProcess(processId: string): Promise<ProcessSummary> {
    return request(`/processes/${processId}/complete`, (data) =>
      ProcessSummarySchema.parse(data),
      { method: "POST", body: "{}" },
    );
  },
  proposeExecutionAction(processId: string, runId?: string): Promise<any> {
    const url = runId
      ? `/processes/${processId}/execution/propose?run_id=${encodeURIComponent(runId)}`
      : `/processes/${processId}/execution/propose`;
    return request(url, (res) => res, { method: "POST" });
  },
  invokeTool(
    processId: string,
    toolName: string,
    toolArgs: Record<string, unknown>,
    runId?: string,
  ): Promise<any> {
    return request(`/processes/${processId}/execution/tools`, (res) => res, {
      method: "POST",
      body: JSON.stringify({
        tool_name: toolName,
        arguments: toolArgs,
        process_run_id: runId,
      }),
    });
  },
  listApprovals(): Promise<ApprovalSummary[]> {
    return request("/approvals/summaries", (data) =>
      ApprovalSummarySchema.array().parse(data),
    );
  },
  decideApproval(
    approvalId: string,
    body: { decision: "approved" | "rejected"; note?: string; row_version: number },
  ): Promise<any> {
    return request(`/approvals/${approvalId}/decision`, (res) => res, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  getApproval(approvalId: string): Promise<any> {
    return request(`/approvals/${approvalId}`, (res) => res);
  },
  listNotifications(): Promise<Notification[]> {
    return request("/notifications", (data) => NotificationSchema.array().parse(data));
  },
  markNotificationRead(id: string): Promise<Notification> {
    return request(`/notifications/${id}/read`, (data) => NotificationSchema.parse(data), {
      method: "POST",
      body: "{}",
    });
  },
  listCalendarEvents(processId?: string): Promise<CalendarEvent[]> {
    const q = processId ? `?process_id=${encodeURIComponent(processId)}` : "";
    return request(`/calendar-events${q}`, (data) => CalendarEventSchema.array().parse(data));
  },
  listTasks(processId?: string): Promise<TaskItem[]> {
    const q = processId ? `?process_id=${encodeURIComponent(processId)}` : "";
    return request(`/tasks${q}`, (data) => TaskItemSchema.array().parse(data));
  },
  listGeneratedDocuments(processId?: string): Promise<GeneratedDocument[]> {
    const q = processId ? `?process_id=${encodeURIComponent(processId)}` : "";
    return request(`/generated-documents${q}`, (data) =>
      GeneratedDocumentSchema.array().parse(data),
    );
  },
  getGeneratedDocument(id: string): Promise<GeneratedDocument> {
    return request(`/generated-documents/${id}`, (data) => GeneratedDocumentSchema.parse(data));
  },
  listEmails(processId?: string): Promise<EmailMessage[]> {
    const q = processId ? `?process_id=${encodeURIComponent(processId)}` : "";
    return request(`/emails${q}`, (data) => EmailMessageSchema.array().parse(data));
  },
  listBillingPlans(): Promise<BillingPlansResponse> {
    return request("/billing/plans", (data) => BillingPlansResponseSchema.parse(data));
  },
  getBillingSubscription(): Promise<BillingSubscriptionSnapshot> {
    return request("/billing/subscription", (data) =>
      BillingSubscriptionSnapshotSchema.parse(data),
    );
  },
  getBillingUsage(): Promise<BillingUsageResponse> {
    return request("/billing/usage", (data) => BillingUsageResponseSchema.parse(data));
  },
  upgradePlan(plan_code: string): Promise<BillingSubscriptionSnapshot> {
    return request("/billing/subscription/upgrade", (data) =>
      BillingSubscriptionSnapshotSchema.parse(data),
      {
        method: "POST",
        body: JSON.stringify({ plan_code }),
      },
    );
  },
  downgradePlan(plan_code: string): Promise<BillingSubscriptionSnapshot> {
    return request("/billing/subscription/downgrade", (data) =>
      BillingSubscriptionSnapshotSchema.parse(data),
      {
        method: "POST",
        body: JSON.stringify({ plan_code }),
      },
    );
  },
  cancelSubscription(at_period_end = true): Promise<BillingSubscriptionSnapshot> {
    return request("/billing/subscription/cancel", (data) =>
      BillingSubscriptionSnapshotSchema.parse(data),
      {
        method: "POST",
        body: JSON.stringify({ at_period_end }),
      },
    );
  },
  listAuditEvents(options?: { limit?: number; offset?: number; action?: string }): Promise<{
    items: AuditEvent[];
    meta: { total: number; limit: number; offset: number };
  }> {
    const params = new URLSearchParams();
    if (options?.limit != null) params.set("limit", String(options.limit));
    if (options?.offset != null) params.set("offset", String(options.offset));
    if (options?.action) params.set("action", options.action);
    const q = params.toString() ? `?${params.toString()}` : "";
    return request(`/audit-events${q}`, (data) => PageSchema(AuditEventSchema).parse(data));
  },
  listProcessRuns(options?: { limit?: number; offset?: number }): Promise<{
    items: ProcessRun[];
    meta: { total: number; limit: number; offset: number };
  }> {
    const params = new URLSearchParams();
    if (options?.limit != null) params.set("limit", String(options.limit));
    if (options?.offset != null) params.set("offset", String(options.offset));
    const q = params.toString() ? `?${params.toString()}` : "";
    return request(`/process-runs${q}`, (data) => PageSchema(ProcessRunSchema).parse(data));
  },
  processRunEventsUrl(runId: string): string {
    if (useMock()) return `mock://process-runs/${runId}/events`;
    const orgId = sessionStore.getOrganizationId() ?? "";
    const token = sessionStore.getToken() ?? "";
    const base = getApiBaseUrl();
    return `${base}/process-runs/${runId}/events?access_token=${encodeURIComponent(token)}&organization_id=${encodeURIComponent(orgId)}`;
  },
};
