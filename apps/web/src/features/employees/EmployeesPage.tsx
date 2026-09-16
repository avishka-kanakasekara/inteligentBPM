import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CsvImportPanel } from "../../components/management/CsvImportPanel";
import { EmptyState } from "../../components/ui/EmptyState";
import { LoadingState } from "../../components/ui/LoadingState";
import { RetryState } from "../../components/ui/RetryState";
import { RequirePermission } from "../../components/RouteGuards";
import { apiClient } from "../../lib/apiClient";
import { PERMISSIONS, permissionsForRole } from "../../lib/permissions";
import { useOrganization } from "../../providers/OrganizationProvider";

const employeeSchema = z.object({
  full_name: z.string().min(1, "Name is required"),
  email: z.string().email("Valid email required"),
  title: z.string().optional(),
  role_code: z.string().optional(),
  is_manager: z.boolean().optional(),
  approval_authority_limit: z.coerce.number().optional(),
});

type EmployeeForm = z.infer<typeof employeeSchema>;

const SAMPLE_CSV = `full_name,email,title,is_manager,role_code,approval_authority_limit
Jordan Lead,jordan@demo.test,Team Lead,true,manager,2500
Riley Buyer,riley@demo.test,Buyer,false,employee,`;

export function EmployeesPage() {
  const { activeOrganization } = useOrganization();
  const canManage =
    activeOrganization &&
    permissionsForRole(activeOrganization.membership_role).has(PERMISSIONS.DIRECTORY_MANAGE);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("active");
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
    defaultValues: {
      full_name: "",
      email: "",
      title: "",
      role_code: "employee",
      is_manager: false,
    },
  });

  const createMutation = useMutation({
    mutationFn: (values: EmployeeForm) => apiClient.createEmployee(values),
    onSuccess: () => {
      form.reset();
      void queryClient.invalidateQueries({ queryKey: ["employees"] });
    },
  });

  const deactivateMutation = useMutation({
    mutationFn: (id: string) => apiClient.deactivateEmployee(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["employees"] }),
  });

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
          Directory, roles, approval authority, departments, budgets, and cost centers.
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
              placeholder="Name or email"
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
                <th scope="col">Name</th>
                <th scope="col">Email</th>
                <th scope="col">Role</th>
                <th scope="col">Manager</th>
                <th scope="col">Approval limit</th>
                <th scope="col">Status</th>
                {canManage ? <th scope="col">Actions</th> : null}
              </tr>
            </thead>
            <tbody>
              {employeesQuery.data.items.map((row) => (
                <tr key={row.id}>
                  <td>{row.full_name}</td>
                  <td>{row.email}</td>
                  <td>{row.role_code ?? "—"}</td>
                  <td>{row.is_manager ? "Yes" : "No"}</td>
                  <td>
                    {row.approval_authority_limit != null
                      ? `${row.approval_authority_limit} ${row.approval_authority_currency ?? "USD"}`
                      : "—"}
                  </td>
                  <td>
                    <span className={`status-pill ${row.status === "active" ? "tone-success" : "tone-warning"}`}>
                      {row.status}
                    </span>
                  </td>
                  {canManage ? (
                    <td>
                      {row.status === "active" ? (
                        <button
                          type="button"
                          className="linkish"
                          onClick={() => deactivateMutation.mutate(row.id)}
                        >
                          Deactivate
                        </button>
                      ) : (
                        "—"
                      )}
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
              onSubmit={form.handleSubmit((values) => createMutation.mutate(values))}
              noValidate
            >
              <h2>Add employee</h2>
              <div className="form-grid">
                <label>
                  Full name
                  <input {...form.register("full_name")} />
                </label>
                <label>
                  Email
                  <input type="email" {...form.register("email")} />
                </label>
                <label>
                  Title
                  <input {...form.register("title")} />
                </label>
                <label>
                  Role code
                  <input {...form.register("role_code")} />
                </label>
                <label>
                  Approval authority limit
                  <input type="number" step="0.01" {...form.register("approval_authority_limit")} />
                </label>
                <label className="checkbox-row">
                  <input type="checkbox" {...form.register("is_manager")} />
                  Mark as manager
                </label>
              </div>
              <button type="submit" disabled={createMutation.isPending}>
                Create employee
              </button>
              {createMutation.isError ? (
                <p className="field-error" role="alert">
                  {(createMutation.error as Error).message}
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
