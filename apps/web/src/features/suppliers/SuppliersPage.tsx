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

const supplierSchema = z.object({
  name: z.string().min(1),
  code: z.string().optional(),
  approval_status: z.enum(["pending", "approved", "rejected", "suspended"]),
  country_code: z.string().optional(),
});

type SupplierForm = z.infer<typeof supplierSchema>;

const SAMPLE_CSV = `name,code,approval_status,contact_name,contact_email
Acme Parts,AP-1,pending,Lee Contact,lee@acme.test`;

export function SuppliersPage() {
  const { activeOrganization } = useOrganization();
  const canManage =
    activeOrganization &&
    permissionsForRole(activeOrganization.membership_role).has(PERMISSIONS.SUPPLIERS_MANAGE);
  const [status, setStatus] = useState("active");
  const queryClient = useQueryClient();
  const queryString = useMemo(() => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    const qs = params.toString();
    return qs ? `?${qs}` : "";
  }, [status]);

  const suppliersQuery = useQuery({
    queryKey: ["suppliers", queryString, activeOrganization?.id],
    queryFn: () => apiClient.listSuppliers(queryString),
    enabled: Boolean(activeOrganization?.id),
  });
  const contactsQuery = useQuery({
    queryKey: ["supplier-contacts", activeOrganization?.id],
    queryFn: () => apiClient.listSupplierContacts(),
    enabled: Boolean(activeOrganization?.id),
  });
  const productsQuery = useQuery({
    queryKey: ["supplier-products", activeOrganization?.id],
    queryFn: () => apiClient.listSupplierProducts(),
    enabled: Boolean(activeOrganization?.id),
  });

  const form = useForm<SupplierForm>({
    resolver: zodResolver(supplierSchema),
    defaultValues: { name: "", code: "", approval_status: "pending" },
  });

  const createMutation = useMutation({
    mutationFn: (values: SupplierForm) => apiClient.createSupplier(values),
    onSuccess: () => {
      form.reset({ name: "", code: "", approval_status: "pending" });
      void queryClient.invalidateQueries({ queryKey: ["suppliers"] });
    },
  });

  const approveMutation = useMutation({
    mutationFn: (id: string) =>
      apiClient.updateSupplier(id, { approval_status: "approved" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["suppliers"] }),
  });

  const deactivateMutation = useMutation({
    mutationFn: (id: string) => apiClient.deactivateSupplier(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["suppliers"] }),
  });

  return (
    <RequirePermission
      permission={PERMISSIONS.SUPPLIERS_READ}
      fallback={
        <EmptyState
          title="Access restricted"
          description="Supplier directory is hidden for your role."
        />
      }
    >
      <section>
        <h1>Suppliers</h1>
        <p className="lede">
          Suppliers, contacts, products, and approval status. Unapproved suppliers are never
          treated as approved.
        </p>

        <div className="toolbar">
          <label>
            Status
            <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter suppliers">
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
              <option value="">All</option>
            </select>
          </label>
        </div>

        {suppliersQuery.isLoading ? <LoadingState label="Loading suppliers…" /> : null}
        {suppliersQuery.isError ? (
          <RetryState
            title="Could not load suppliers"
            message="Retry to reload the supplier directory."
            onRetry={() => void suppliersQuery.refetch()}
          />
        ) : null}
        {suppliersQuery.data?.items.length === 0 ? (
          <EmptyState title="No suppliers" description="Add or import suppliers to begin." />
        ) : null}

        {suppliersQuery.data && suppliersQuery.data.items.length > 0 ? (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Code</th>
                <th scope="col">Approval</th>
                <th scope="col">Status</th>
                {canManage ? <th scope="col">Actions</th> : null}
              </tr>
            </thead>
            <tbody>
              {suppliersQuery.data.items.map((s) => (
                <tr key={s.id}>
                  <td>{s.name}</td>
                  <td>{s.code ?? "—"}</td>
                  <td>
                    <span
                      className={`status-pill ${
                        s.approval_status === "approved"
                          ? "tone-success"
                          : s.approval_status === "pending"
                            ? "tone-warning"
                            : "tone-danger"
                      }`}
                    >
                      {s.approval_status}
                    </span>
                  </td>
                  <td>{s.status}</td>
                  {canManage ? (
                    <td className="button-row">
                      {s.approval_status !== "approved" && s.status === "active" ? (
                        <button type="button" onClick={() => approveMutation.mutate(s.id)}>
                          Mark approved
                        </button>
                      ) : null}
                      {s.status === "active" ? (
                        <button type="button" onClick={() => deactivateMutation.mutate(s.id)}>
                          Deactivate
                        </button>
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
              className="mgmt-form"
              onSubmit={form.handleSubmit((values) => createMutation.mutate(values))}
              noValidate
            >
              <h2>Add supplier</h2>
              <div className="form-grid">
                <label>
                  Name
                  <input {...form.register("name")} />
                </label>
                <label>
                  Code
                  <input {...form.register("code")} />
                </label>
                <label>
                  Approval status
                  <select {...form.register("approval_status")}>
                    <option value="pending">pending</option>
                    <option value="approved">approved</option>
                    <option value="rejected">rejected</option>
                    <option value="suspended">suspended</option>
                  </select>
                </label>
              </div>
              <button type="submit">Create supplier</button>
            </form>

            <CsvImportPanel
              title="Import suppliers (CSV)"
              sampleCsv={SAMPLE_CSV}
              onPreview={(csv) => apiClient.previewSupplierImport(csv)}
              onCommit={(csv) => apiClient.commitSupplierImport(csv)}
              onCommitted={() => {
                void queryClient.invalidateQueries({ queryKey: ["suppliers"] });
                void queryClient.invalidateQueries({ queryKey: ["supplier-contacts"] });
              }}
            />
          </>
        ) : null}

        <div className="split-panels" style={{ marginTop: "1.5rem" }}>
          <article>
            <h2>Contacts</h2>
            <ul className="simple-list">
              {(contactsQuery.data?.items ?? []).map((c) => (
                <li key={c.id}>
                  {c.full_name} — {c.email ?? "no email"} ({c.status})
                </li>
              ))}
            </ul>
          </article>
          <article>
            <h2>Products</h2>
            <ul className="simple-list">
              {(productsQuery.data?.items ?? []).map((p) => (
                <li key={p.id}>
                  {p.name} {p.sku ? `(${p.sku})` : ""} — {p.unit_price ?? "—"} {p.currency_code}
                </li>
              ))}
            </ul>
          </article>
        </div>
      </section>
    </RequirePermission>
  );
}
