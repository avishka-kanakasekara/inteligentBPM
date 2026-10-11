import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Employee } from "@bpm/frontend-types";
import { CsvImportPanel } from "../../components/management/CsvImportPanel";
import { EmptyState } from "../../components/ui/EmptyState";
import { LoadingState } from "../../components/ui/LoadingState";
import { RetryState } from "../../components/ui/RetryState";
import { RequirePermission } from "../../components/RouteGuards";
import { apiClient } from "../../lib/apiClient";
import { PERMISSIONS, permissionsForRole } from "../../lib/permissions";
import { useOrganization } from "../../providers/OrganizationProvider";

function optionalNumber(rule: z.ZodNumber) {
  return z.preprocess((value) => {
    if (value === "" || value === null || value === undefined) return undefined;
    if (typeof value === "number") return Number.isFinite(value) ? value : value;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : value;
  }, rule.optional());
}

const employeeSchema = z
  .object({
    full_name: z.string().min(1, "Name is required"),
    email: z.string().email("Valid email required"),
    phone: z.string().optional(),
    department_id: z.string().optional(),
    title: z.string().optional(),
    employment_type: z.enum(["full_time", "part_time", "contract"]),
    join_date: z.string().optional(),
    status: z.enum(["active", "inactive"]),
    manager_employee_id: z.string().optional(),
    team: z.string().optional(),
    business_unit: z.string().optional(),
    location: z.string().optional(),
    reporting_level: optionalNumber(z.number().int().min(1, "Reporting level starts at 1")),
    is_manager: z.boolean().optional(),
    role_code: z.string().optional(),
    primary_skills: z.string().optional(),
    secondary_skills: z.string().optional(),
    certifications: z.string().optional(),
    years_of_experience: optionalNumber(z.number().min(0, "Experience cannot be negative")),
    skill_level: z.enum(["beginner", "intermediate", "expert"]),
    availability_percent: optionalNumber(z.number().min(0).max(100, "Use 0–100")),
    weekly_capacity_hours: optionalNumber(z.number().min(0).max(168, "Maximum is 168 hours")),
    baseline_workload_percent: optionalNumber(z.number().min(0).max(100, "Use 0–100")),
    cost_per_hour: optionalNumber(z.number().min(0, "Cost cannot be negative")),
    monthly_cost: optionalNumber(z.number().min(0, "Cost cannot be negative")),
    max_allocation_percent: optionalNumber(z.number().min(0).max(100, "Use 0–100")),
    approval_authority_limit: optionalNumber(z.number().min(0, "Limit cannot be negative")),
    approval_tier: z.enum(["none", "team", "department", "business_unit", "executive"]),
    can_approve_procurement: z.boolean().optional(),
    can_approve_budget: z.boolean().optional(),
    delegation_authority: z.boolean().optional(),
    tasks_completed: optionalNumber(z.number().int().min(0)),
    avg_task_completion_hours: optionalNumber(z.number().min(0)),
    sla_compliance_percent: optionalNumber(z.number().min(0).max(100, "Use 0–100")),
    performance_score: optionalNumber(z.number().min(0).max(100, "Use 0–100")),
  })
  .superRefine((values, ctx) => {
    const workload = values.baseline_workload_percent ?? 0;
    const maximum = values.max_allocation_percent ?? 100;
    if (workload > maximum) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["baseline_workload_percent"],
        message: "Baseline workload cannot exceed the maximum allocation",
      });
    }
  });

type EmployeeForm = z.infer<typeof employeeSchema>;

const EMPTY_FORM: EmployeeForm = {
  full_name: "",
  email: "",
  phone: "",
  department_id: "",
  title: "",
  employment_type: "full_time",
  join_date: "",
  status: "active",
  manager_employee_id: "",
  team: "",
  business_unit: "",
  location: "",
  reporting_level: 1,
  is_manager: false,
  role_code: "employee",
  primary_skills: "",
  secondary_skills: "",
  certifications: "",
  years_of_experience: undefined,
  skill_level: "intermediate",
  availability_percent: 100,
  weekly_capacity_hours: 40,
  baseline_workload_percent: 0,
  cost_per_hour: undefined,
  monthly_cost: undefined,
  max_allocation_percent: 100,
  approval_authority_limit: undefined,
  approval_tier: "none",
  can_approve_procurement: false,
  can_approve_budget: false,
  delegation_authority: false,
  tasks_completed: undefined,
  avg_task_completion_hours: undefined,
  sla_compliance_percent: undefined,
  performance_score: undefined,
};

const SAMPLE_CSV = `full_name,email,title,is_manager,role_code,approval_authority_limit
Jordan Lead,jordan@demo.test,Team Lead,true,manager,2500
Riley Buyer,riley@demo.test,Buyer,false,employee,`;

function splitList(value: string | undefined): string[] {
  return (value ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function emptyToNull(value: string | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

function toPayload(values: EmployeeForm): Record<string, unknown> {
  return {
    full_name: values.full_name.trim(),
    email: values.email.trim(),
    phone: emptyToNull(values.phone),
    department_id: emptyToNull(values.department_id),
    title: emptyToNull(values.title),
    employment_type: values.employment_type,
    join_date: emptyToNull(values.join_date),
    status: values.status,
    manager_employee_id: emptyToNull(values.manager_employee_id),
    team: emptyToNull(values.team),
    business_unit: emptyToNull(values.business_unit),
    location: emptyToNull(values.location),
    reporting_level: values.reporting_level ?? 1,
    is_manager: Boolean(values.is_manager),
    role_code: emptyToNull(values.role_code),
    primary_skills: splitList(values.primary_skills),
    secondary_skills: splitList(values.secondary_skills),
    certifications: splitList(values.certifications),
    years_of_experience: values.years_of_experience ?? null,
    skill_level: values.skill_level,
    availability_percent: values.availability_percent ?? 100,
    weekly_capacity_hours: values.weekly_capacity_hours ?? 40,
    baseline_workload_percent: values.baseline_workload_percent ?? 0,
    cost_per_hour: values.cost_per_hour ?? null,
    monthly_cost: values.monthly_cost ?? null,
    max_allocation_percent: values.max_allocation_percent ?? 100,
    approval_authority_limit: values.approval_authority_limit ?? null,
    approval_authority_currency: "USD",
    approval_tier: values.approval_tier,
    can_approve_procurement: Boolean(values.can_approve_procurement),
    can_approve_budget: Boolean(values.can_approve_budget),
    delegation_authority: Boolean(values.delegation_authority),
    tasks_completed: values.tasks_completed ?? null,
    avg_task_completion_hours: values.avg_task_completion_hours ?? null,
    sla_compliance_percent: values.sla_compliance_percent ?? null,
    performance_score: values.performance_score ?? null,
  };
}

function formFromEmployee(employee: Employee): EmployeeForm {
  return {
    ...EMPTY_FORM,
    full_name: employee.full_name,
    email: employee.email,
    phone: employee.phone ?? "",
    department_id: employee.department_id ?? "",
    title: employee.title ?? "",
    employment_type: employee.employment_type ?? "full_time",
    join_date: employee.join_date?.slice(0, 10) ?? "",
    status: employee.status === "inactive" ? "inactive" : "active",
    manager_employee_id: employee.manager_employee_id ?? "",
    team: employee.team ?? "",
    business_unit: employee.business_unit ?? "",
    location: employee.location ?? "",
    reporting_level: employee.reporting_level ?? 1,
    is_manager: employee.is_manager,
    role_code: employee.role_code ?? "",
    primary_skills: (employee.primary_skills ?? []).join(", "),
    secondary_skills: (employee.secondary_skills ?? []).join(", "),
    certifications: (employee.certifications ?? []).join(", "),
    years_of_experience: employee.years_of_experience ?? undefined,
    skill_level: employee.skill_level ?? "intermediate",
    availability_percent: employee.availability_percent ?? 100,
    weekly_capacity_hours: employee.weekly_capacity_hours ?? 40,
    baseline_workload_percent: employee.baseline_workload_percent ?? 0,
    cost_per_hour: employee.cost_per_hour ?? undefined,
    monthly_cost: employee.monthly_cost ?? undefined,
    max_allocation_percent: employee.max_allocation_percent ?? 100,
    approval_authority_limit: employee.approval_authority_limit ?? undefined,
    approval_tier: employee.approval_tier ?? "none",
    can_approve_procurement: employee.can_approve_procurement ?? false,
    can_approve_budget: employee.can_approve_budget ?? false,
    delegation_authority: employee.delegation_authority ?? false,
    tasks_completed: employee.tasks_completed ?? undefined,
    avg_task_completion_hours: employee.avg_task_completion_hours ?? undefined,
    sla_compliance_percent: employee.sla_compliance_percent ?? undefined,
    performance_score: employee.performance_score ?? undefined,
  };
}

function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return (
    <span className="field-error" role="alert">
      {message}
    </span>
  );
}

export function EmployeesPage() {
  const { activeOrganization } = useOrganization();
  const canManage =
    activeOrganization &&
    permissionsForRole(activeOrganization.membership_role).has(PERMISSIONS.DIRECTORY_MANAGE);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("active");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [calculatedWorkload, setCalculatedWorkload] = useState<number | null>(null);
  const queryClient = useQueryClient();

  const queryString = useMemo(() => {
    const params = new URLSearchParams();
    if (search) params.set("q", search);
    if (status) params.set("status", status);
    const qs = params.toString();
    return qs ? `?${qs}` : "";
  }, [search, status]);

  const employeesQuery = useQuery({
    queryKey: ["employees", queryString, activeOrganization?.id],
    queryFn: () => apiClient.listEmployees(queryString),
    enabled: Boolean(activeOrganization?.id),
  });

  const managerOptionsQuery = useQuery({
    queryKey: ["employees", "options", activeOrganization?.id],
    queryFn: () => apiClient.listEmployees("?limit=200"),
    enabled: Boolean(activeOrganization?.id) && Boolean(canManage),
  });

  const departmentsQuery = useQuery({
    queryKey: ["departments", activeOrganization?.id],
    queryFn: () => apiClient.listDepartments(),
    enabled: Boolean(activeOrganization?.id),
  });

  const costCentersQuery = useQuery({
    queryKey: ["cost-centers", activeOrganization?.id],
    queryFn: () => apiClient.listCostCenters(),
    enabled: Boolean(activeOrganization?.id),
  });

  const budgetsQuery = useQuery({
    queryKey: ["budgets", activeOrganization?.id],
    queryFn: () => apiClient.listBudgets(),
    enabled: Boolean(activeOrganization?.id),
  });

  const form = useForm<EmployeeForm>({
    resolver: zodResolver(employeeSchema),
    defaultValues: EMPTY_FORM,
  });

  const departmentName = useMemo(() => {
    const map = new Map<string, string>();
    for (const department of departmentsQuery.data?.items ?? []) {
      map.set(department.id, department.name);
    }
    return map;
  }, [departmentsQuery.data?.items]);

  const saveMutation = useMutation({
    mutationFn: (values: EmployeeForm) => {
      const payload = toPayload(values);
      return editingId
        ? apiClient.updateEmployee(editingId, payload)
        : apiClient.createEmployee(payload);
    },
    onSuccess: () => {
      setEditingId(null);
      setCalculatedWorkload(null);
      form.reset(EMPTY_FORM);
      void queryClient.invalidateQueries({ queryKey: ["employees"] });
    },
  });

  const deactivateMutation = useMutation({
    mutationFn: (id: string) => apiClient.deactivateEmployee(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["employees"] }),
  });

  function beginEdit(employee: Employee) {
    setEditingId(employee.id);
    setCalculatedWorkload(employee.current_workload_percent ?? 0);
    form.reset(formFromEmployee(employee));
    document.getElementById("add-employee")?.scrollIntoView({ behavior: "smooth" });
  }

  const errors = form.formState.errors;

  return (
    <RequirePermission
      permission={PERMISSIONS.DIRECTORY_READ}
      fallback={
        <EmptyState
          title="Access restricted"
          description="You do not have permission to view the employee directory."
        />
      }
    >
      <section>
        <h1>Employees and managers</h1>
        <p className="lede">
          Workforce profiles for workflow routing, approval limits, capacity planning, and later
          resource recommendations.
        </p>

        <div className="page-header-actions" style={{ marginBottom: "1rem" }}>
          {canManage ? (
            <>
              <a href="#add-employee" className="btn btn-primary">
                Add employee
              </a>
              <a href="#import-employees" className="ghost-btn">
                Import CSV
              </a>
            </>
          ) : null}
        </div>

        <div className="toolbar">
          <label>
            Search
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Name, email, title, or employee ID"
              aria-label="Search employees"
            />
          </label>
          <label>
            Status
            <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter status">
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
              <option value="">All</option>
            </select>
          </label>
        </div>

        {employeesQuery.isLoading ? <LoadingState label="Loading employees…" /> : null}
        {employeesQuery.isError ? (
          <RetryState
            title="Could not load employees"
            message="Retry to reload the directory."
            onRetry={() => void employeesQuery.refetch()}
          />
        ) : null}
        {employeesQuery.data && employeesQuery.data.items.length === 0 ? (
          <EmptyState title="No employees" description="Import a CSV or add an employee." />
        ) : null}
        {employeesQuery.data && employeesQuery.data.items.length > 0 ? (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Employee ID</th>
                <th scope="col">Name</th>
                <th scope="col">Title</th>
                <th scope="col">Department</th>
                <th scope="col">Skills</th>
                <th scope="col">Availability</th>
                <th scope="col">Workload</th>
                <th scope="col">Status</th>
                {canManage ? <th scope="col">Actions</th> : null}
              </tr>
            </thead>
            <tbody>
              {employeesQuery.data.items.map((row) => (
                <tr key={row.id}>
                  <td>{row.employee_code ?? "—"}</td>
                  <td>
                    <strong>{row.full_name}</strong>
                    <div>{row.email}</div>
                  </td>
                  <td>{row.title ?? "—"}</td>
                  <td>{row.department_id ? departmentName.get(row.department_id) ?? "—" : "—"}</td>
                  <td>{(row.primary_skills ?? []).slice(0, 3).join(", ") || "—"}</td>
                  <td>{row.availability_percent ?? 100}%</td>
                  <td>{row.current_workload_percent ?? 0}%</td>
                  <td>
                    <span className={`status-pill ${row.status === "active" ? "tone-success" : "tone-warning"}`}>
                      {row.status}
                    </span>
                  </td>
                  {canManage ? (
                    <td>
                      <button type="button" className="linkish" onClick={() => beginEdit(row)}>
                        Edit
                      </button>
                      {row.status === "active" ? (
                        <>
                          {" · "}
                          <button
                            type="button"
                            className="linkish"
                            onClick={() => deactivateMutation.mutate(row.id)}
                          >
                            Deactivate
                          </button>
                        </>
                      ) : null}
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}

        {canManage ? (
          <>
            <form
              id="add-employee"
              className="mgmt-form"
              onSubmit={form.handleSubmit((values) => saveMutation.mutate(values))}
              noValidate
            >
              <h2>{editingId ? "Edit employee" : "Add employee"}</h2>
              <p className="section-hint">
                {editingId
                  ? "Employee ID stays the same. Capacity and skills are available to later allocation recommendations."
                  : "Employee ID is assigned automatically when you save."}
              </p>

              <div className="form-sections">
                <section className="form-section">
                  <h3>Basic information</h3>
                  <p className="section-hint">Who they are and whether they can be assigned to work.</p>
                  <div className="form-grid">
                    <label>
                      Full name
                      <input {...form.register("full_name")} />
                      <FieldError message={errors.full_name?.message} />
                    </label>
                    <label>
                      Email
                      <input type="email" {...form.register("email")} />
                      <FieldError message={errors.email?.message} />
                    </label>
                    <label>
                      Phone number
                      <input {...form.register("phone")} placeholder="+1 202 555 0100" />
                    </label>
                    <label>
                      Department
                      <select {...form.register("department_id")}>
                        <option value="">No department</option>
                        {(departmentsQuery.data?.items ?? []).map((department) => (
                          <option key={department.id} value={department.id}>
                            {department.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Job title
                      <input {...form.register("title")} />
                    </label>
                    <label>
                      Employment type
                      <select {...form.register("employment_type")}>
                        <option value="full_time">Full time</option>
                        <option value="part_time">Part time</option>
                        <option value="contract">Contract</option>
                      </select>
                    </label>
                    <label>
                      Join date
                      <input type="date" {...form.register("join_date")} />
                    </label>
                    <label>
                      Status
                      <select {...form.register("status")}>
                        <option value="active">Active</option>
                        <option value="inactive">Inactive</option>
                      </select>
                    </label>
                  </div>
                </section>

                <section className="form-section">
                  <h3>Organizational information</h3>
                  <p className="section-hint">Reporting line used for approval routing.</p>
                  <div className="form-grid">
                    <label>
                      Manager
                      <select {...form.register("manager_employee_id")}>
                        <option value="">No manager</option>
                        {(managerOptionsQuery.data?.items ?? [])
                          .filter((employee) => employee.id !== editingId && employee.status === "active")
                          .map((employee) => (
                            <option key={employee.id} value={employee.id}>
                              {employee.full_name}
                            </option>
                          ))}
                      </select>
                    </label>
                    <label>
                      Team
                      <input {...form.register("team")} />
                    </label>
                    <label>
                      Business unit
                      <input {...form.register("business_unit")} />
                    </label>
                    <label>
                      Location
                      <input {...form.register("location")} />
                    </label>
                    <label>
                      Reporting level
                      <input type="number" min={1} step={1} {...form.register("reporting_level")} />
                      <FieldError message={errors.reporting_level?.message} />
                    </label>
                    <label>
                      Role code
                      <input {...form.register("role_code")} />
                    </label>
                    <label className="checkbox-row">
                      <input type="checkbox" {...form.register("is_manager")} />
                      This person is a manager
                    </label>
                  </div>
                </section>

                <section className="form-section">
                  <h3>Skills and competencies</h3>
                  <p className="section-hint">Separate multiple values with commas.</p>
                  <div className="form-grid">
                    <label className="span-2">
                      Primary skills
                      <input {...form.register("primary_skills")} placeholder="procurement, negotiation" />
                    </label>
                    <label className="span-2">
                      Secondary skills
                      <input {...form.register("secondary_skills")} placeholder="excel, vendor management" />
                    </label>
                    <label className="span-2">
                      Certifications
                      <input {...form.register("certifications")} placeholder="PMP, ITIL" />
                    </label>
                    <label>
                      Years of experience
                      <input type="number" min={0} step="0.5" {...form.register("years_of_experience")} />
                      <FieldError message={errors.years_of_experience?.message} />
                    </label>
                    <label>
                      Skill level
                      <select {...form.register("skill_level")}>
                        <option value="beginner">Beginner</option>
                        <option value="intermediate">Intermediate</option>
                        <option value="expert">Expert</option>
                      </select>
                    </label>
                  </div>
                </section>

                <section className="form-section">
                  <h3>Resource allocation</h3>
                  <p className="section-hint">
                    Capacity and cost used when recommending who can take new work.
                  </p>
                  <div className="form-grid">
                    <label>
                      Availability %
                      <input type="number" min={0} max={100} step="1" {...form.register("availability_percent")} />
                      <FieldError message={errors.availability_percent?.message} />
                    </label>
                    <label>
                      Weekly capacity (hours)
                      <input type="number" min={0} max={168} step="0.5" {...form.register("weekly_capacity_hours")} />
                      <FieldError message={errors.weekly_capacity_hours?.message} />
                    </label>
                    <label>
                      Baseline workload %
                      <input
                        type="number"
                        min={0}
                        max={100}
                        step="1"
                        {...form.register("baseline_workload_percent")}
                      />
                      <FieldError message={errors.baseline_workload_percent?.message} />
                    </label>
                    <label>
                      Calculated workload %
                      <input
                        type="text"
                        readOnly
                        value={`${calculatedWorkload ?? form.watch("baseline_workload_percent") ?? 0}%`}
                        aria-label="Calculated workload percent"
                      />
                    </label>
                    <label>
                      Maximum allocation %
                      <input type="number" min={0} max={100} step="1" {...form.register("max_allocation_percent")} />
                      <FieldError message={errors.max_allocation_percent?.message} />
                    </label>
                    <label>
                      Cost per hour (USD)
                      <input type="number" min={0} step="0.01" {...form.register("cost_per_hour")} />
                      <FieldError message={errors.cost_per_hour?.message} />
                    </label>
                    <label>
                      Monthly cost (USD)
                      <input type="number" min={0} step="0.01" {...form.register("monthly_cost")} />
                      <FieldError message={errors.monthly_cost?.message} />
                    </label>
                  </div>
                </section>

                <section className="form-section">
                  <h3>Approval and governance</h3>
                  <p className="section-hint">Limits that decide who can approve spend and budget.</p>
                  <div className="form-grid">
                    <label>
                      Approval authority limit (USD)
                      <input type="number" min={0} step="0.01" {...form.register("approval_authority_limit")} />
                      <FieldError message={errors.approval_authority_limit?.message} />
                    </label>
                    <label>
                      Approval tier
                      <select {...form.register("approval_tier")}>
                        <option value="none">None</option>
                        <option value="team">Team</option>
                        <option value="department">Department</option>
                        <option value="business_unit">Business unit</option>
                        <option value="executive">Executive</option>
                      </select>
                    </label>
                    <label className="checkbox-row">
                      <input type="checkbox" {...form.register("can_approve_procurement")} />
                      Can approve procurement
                    </label>
                    <label className="checkbox-row">
                      <input type="checkbox" {...form.register("can_approve_budget")} />
                      Can approve budget
                    </label>
                    <label className="checkbox-row">
                      <input type="checkbox" {...form.register("delegation_authority")} />
                      Delegation authority
                    </label>
                  </div>
                </section>

                <section className="form-section">
                  <h3>Performance metrics</h3>
                  <p className="section-hint">Optional. Leave blank until execution history is available.</p>
                  <div className="form-grid">
                    <label>
                      Tasks completed
                      <input type="number" min={0} step={1} {...form.register("tasks_completed")} />
                    </label>
                    <label>
                      Average completion time (hours)
                      <input type="number" min={0} step="0.1" {...form.register("avg_task_completion_hours")} />
                    </label>
                    <label>
                      SLA compliance %
                      <input type="number" min={0} max={100} step="0.1" {...form.register("sla_compliance_percent")} />
                      <FieldError message={errors.sla_compliance_percent?.message} />
                    </label>
                    <label>
                      Performance score
                      <input type="number" min={0} max={100} step="0.1" {...form.register("performance_score")} />
                      <FieldError message={errors.performance_score?.message} />
                    </label>
                  </div>
                </section>
              </div>

              <div className="page-header-actions">
                <button type="submit" disabled={saveMutation.isPending}>
                  {saveMutation.isPending ? "Saving…" : editingId ? "Save changes" : "Create employee"}
                </button>
                {editingId ? (
                  <button
                    type="button"
                    className="ghost-btn"
                    onClick={() => {
                      setEditingId(null);
                      form.reset(EMPTY_FORM);
                    }}
                  >
                    Cancel
                  </button>
                ) : null}
              </div>
              {saveMutation.isError ? (
                <p className="field-error" role="alert">
                  {(saveMutation.error as Error).message}
                </p>
              ) : null}
            </form>

            <div id="import-employees">
              <CsvImportPanel
                title="Import employees (CSV)"
                sampleCsv={SAMPLE_CSV}
                onPreview={(csv) => apiClient.previewEmployeeImport(csv)}
                onCommit={(csv) => apiClient.commitEmployeeImport(csv)}
                onCommitted={() => void queryClient.invalidateQueries({ queryKey: ["employees"] })}
              />
            </div>
          </>
        ) : null}

        <div className="split-panels" style={{ marginTop: "1.5rem" }}>
          <article>
            <h2>Departments</h2>
            <ul className="simple-list">
              {(departmentsQuery.data?.items ?? []).map((d) => (
                <li key={d.id}>
                  {d.name} {d.code ? `(${d.code})` : ""} — {d.status}
                </li>
              ))}
            </ul>
          </article>
          <article>
            <h2>Cost centers</h2>
            <ul className="simple-list">
              {(costCentersQuery.data?.items ?? []).map((c) => (
                <li key={c.id}>
                  {c.code} — {c.name} ({c.status})
                </li>
              ))}
            </ul>
          </article>
          <article>
            <h2>Budgets</h2>
            <ul className="simple-list">
              {(budgetsQuery.data?.items ?? []).map((b) => (
                <li key={b.id}>
                  {b.name} FY{b.fiscal_year}: {b.amount_total} {b.currency_code}
                </li>
              ))}
            </ul>
          </article>
        </div>
      </section>
    </RequirePermission>
  );
}
