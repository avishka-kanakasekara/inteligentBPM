import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Supplier } from "@bpm/frontend-types";
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

const supplierSchema = z
  .object({
    name: z.string().min(1, "Company name is required"),
    code: z.string().optional(),
    status: z.enum(["active", "inactive"]),
    business_registration_number: z.string().optional(),
    tax_number: z.string().optional(),
    website: z.string().optional(),
    country_code: z.string().optional(),
    city: z.string().optional(),
    address: z.string().optional(),
    primary_contact_name: z.string().optional(),
    primary_contact_email: z.string().email("Enter a valid email").optional().or(z.literal("")),
    primary_contact_phone: z.string().optional(),
    secondary_contact_name: z.string().optional(),
    secondary_contact_email: z.string().email("Enter a valid email").optional().or(z.literal("")),
    secondary_contact_phone: z.string().optional(),
    supplier_category: z.enum([
      "raw_materials",
      "manufacturing",
      "logistics",
      "it_services",
      "consulting",
      "finance",
      "other",
    ]),
    products_services: z.string().optional(),
    lead_time_days: optionalNumber(z.number().int().min(0, "Lead time cannot be negative")),
    minimum_order_quantity: optionalNumber(z.number().min(0, "Quantity cannot be negative")),
    payment_terms: z.string().optional(),
    preferred_currency: z.string().min(3, "Use a 3-letter currency").max(3),
    risk_level: z.enum(["low", "medium", "high"]),
    compliance_status: z.enum(["pending", "compliant", "non_compliant", "expired"]),
    insurance_valid: z.boolean().optional(),
    contract_start_date: z.string().optional(),
    contract_expiry_date: z.string().optional(),
    certification_details: z.string().optional(),
    supplier_rating: optionalNumber(z.number().min(1, "Rating is 1–5").max(5, "Rating is 1–5")),
    on_time_delivery_percent: optionalNumber(z.number().min(0).max(100, "Use 0–100")),
    quality_score_percent: optionalNumber(z.number().min(0).max(100, "Use 0–100")),
    average_response_hours: optionalNumber(z.number().min(0, "Response time cannot be negative")),
    rejected_orders_count: optionalNumber(z.number().int().min(0, "Cannot be negative")),
    total_orders_completed: optionalNumber(z.number().int().min(0, "Cannot be negative")),
    approval_status: z.enum(["pending", "approved", "rejected", "suspended"]),
    approval_tier: z.enum(["none", "team", "department", "business_unit", "executive"]),
    preferred_supplier: z.boolean().optional(),
    blacklisted: z.boolean().optional(),
    suspension_reason: z.string().optional(),
    notes: z.string().optional(),
  })
  .superRefine((values, ctx) => {
    if (
      values.contract_start_date &&
      values.contract_expiry_date &&
      values.contract_expiry_date < values.contract_start_date
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["contract_expiry_date"],
        message: "Expiry cannot be before the start date",
      });
    }
  });

type SupplierForm = z.infer<typeof supplierSchema>;

const EMPTY_FORM: SupplierForm = {
  name: "",
  code: "",
  status: "active",
  business_registration_number: "",
  tax_number: "",
  website: "",
  country_code: "",
  city: "",
  address: "",
  primary_contact_name: "",
  primary_contact_email: "",
  primary_contact_phone: "",
  secondary_contact_name: "",
  secondary_contact_email: "",
  secondary_contact_phone: "",
  supplier_category: "other",
  products_services: "",
  lead_time_days: undefined,
  minimum_order_quantity: undefined,
  payment_terms: "",
  preferred_currency: "USD",
  risk_level: "low",
  compliance_status: "pending",
  insurance_valid: false,
  contract_start_date: "",
  contract_expiry_date: "",
  certification_details: "",
  supplier_rating: undefined,
  on_time_delivery_percent: undefined,
  quality_score_percent: undefined,
  average_response_hours: undefined,
  rejected_orders_count: 0,
  total_orders_completed: 0,
  approval_status: "pending",
  approval_tier: "none",
  preferred_supplier: false,
  blacklisted: false,
  suspension_reason: "",
  notes: "",
};

const SAMPLE_CSV = `name,code,approval_status,contact_name,contact_email
Acme Parts,AP-1,pending,Lee Contact,lee@acme.test`;

function emptyToNull(value: string | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

function toPayload(values: SupplierForm): Record<string, unknown> {
  return {
    name: values.name.trim(),
    code: emptyToNull(values.code),
    status: values.status,
    business_registration_number: emptyToNull(values.business_registration_number),
    tax_number: emptyToNull(values.tax_number),
    website: emptyToNull(values.website),
    country_code: emptyToNull(values.country_code),
    city: emptyToNull(values.city),
    address: emptyToNull(values.address),
    primary_contact_name: emptyToNull(values.primary_contact_name),
    primary_contact_email: emptyToNull(values.primary_contact_email),
    primary_contact_phone: emptyToNull(values.primary_contact_phone),
    secondary_contact_name: emptyToNull(values.secondary_contact_name),
    secondary_contact_email: emptyToNull(values.secondary_contact_email),
    secondary_contact_phone: emptyToNull(values.secondary_contact_phone),
    supplier_category: values.supplier_category,
    products_services: emptyToNull(values.products_services),
    lead_time_days: values.lead_time_days ?? null,
    minimum_order_quantity: values.minimum_order_quantity ?? null,
    payment_terms: emptyToNull(values.payment_terms),
    preferred_currency: values.preferred_currency.trim().toUpperCase() || "USD",
    risk_level: values.risk_level,
    compliance_status: values.compliance_status,
    insurance_valid: Boolean(values.insurance_valid),
    contract_start_date: emptyToNull(values.contract_start_date),
    contract_expiry_date: emptyToNull(values.contract_expiry_date),
    certification_details: emptyToNull(values.certification_details),
    supplier_rating: values.supplier_rating ?? null,
    on_time_delivery_percent: values.on_time_delivery_percent ?? null,
    quality_score_percent: values.quality_score_percent ?? null,
    average_response_hours: values.average_response_hours ?? null,
    rejected_orders_count: values.rejected_orders_count ?? 0,
    total_orders_completed: values.total_orders_completed ?? 0,
    approval_status: values.approval_status,
    approval_tier: values.approval_tier,
    preferred_supplier: Boolean(values.preferred_supplier),
    blacklisted: Boolean(values.blacklisted),
    suspension_reason: emptyToNull(values.suspension_reason),
    notes: emptyToNull(values.notes),
  };
}

function formFromSupplier(supplier: Supplier): SupplierForm {
  return {
    ...EMPTY_FORM,
    name: supplier.name,
    code: supplier.code ?? "",
    status: supplier.status === "inactive" ? "inactive" : "active",
    business_registration_number: supplier.business_registration_number ?? "",
    tax_number: supplier.tax_number ?? "",
    website: supplier.website ?? "",
    country_code: supplier.country_code ?? "",
    city: supplier.city ?? "",
    address: supplier.address ?? "",
    primary_contact_name: supplier.primary_contact_name ?? "",
    primary_contact_email: supplier.primary_contact_email ?? "",
    primary_contact_phone: supplier.primary_contact_phone ?? "",
    secondary_contact_name: supplier.secondary_contact_name ?? "",
    secondary_contact_email: supplier.secondary_contact_email ?? "",
    secondary_contact_phone: supplier.secondary_contact_phone ?? "",
    supplier_category: supplier.supplier_category ?? "other",
    products_services: supplier.products_services ?? "",
    lead_time_days: supplier.lead_time_days ?? undefined,
    minimum_order_quantity: supplier.minimum_order_quantity ?? undefined,
    payment_terms: supplier.payment_terms ?? "",
    preferred_currency: supplier.preferred_currency ?? "USD",
    risk_level: supplier.risk_level ?? "low",
    compliance_status: supplier.compliance_status ?? "pending",
    insurance_valid: supplier.insurance_valid ?? false,
    contract_start_date: supplier.contract_start_date?.slice(0, 10) ?? "",
    contract_expiry_date: supplier.contract_expiry_date?.slice(0, 10) ?? "",
    certification_details: supplier.certification_details ?? "",
    supplier_rating: supplier.supplier_rating ?? undefined,
    on_time_delivery_percent: supplier.on_time_delivery_percent ?? undefined,
    quality_score_percent: supplier.quality_score_percent ?? undefined,
    average_response_hours: supplier.average_response_hours ?? undefined,
    rejected_orders_count: supplier.rejected_orders_count ?? 0,
    total_orders_completed: supplier.total_orders_completed ?? 0,
    approval_status: supplier.approval_status,
    approval_tier: supplier.approval_tier ?? "none",
    preferred_supplier: supplier.preferred_supplier ?? false,
    blacklisted: supplier.blacklisted ?? false,
    suspension_reason: supplier.suspension_reason ?? "",
    notes: supplier.notes ?? "",
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

export function SuppliersPage() {
  const { activeOrganization } = useOrganization();
  const canManage =
    activeOrganization &&
    permissionsForRole(activeOrganization.membership_role).has(PERMISSIONS.SUPPLIERS_MANAGE);
  const [status, setStatus] = useState("active");
  const [editingId, setEditingId] = useState<string | null>(null);
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
    defaultValues: EMPTY_FORM,
  });

  const saveMutation = useMutation({
    mutationFn: (values: SupplierForm) => {
      const payload = toPayload(values);
      return editingId
        ? apiClient.updateSupplier(editingId, payload)
        : apiClient.createSupplier(payload);
    },
    onSuccess: () => {
      setEditingId(null);
      form.reset(EMPTY_FORM);
      void queryClient.invalidateQueries({ queryKey: ["suppliers"] });
    },
  });

  const approveMutation = useMutation({
    mutationFn: (id: string) => apiClient.updateSupplier(id, { approval_status: "approved" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["suppliers"] }),
  });

  const deactivateMutation = useMutation({
    mutationFn: (id: string) => apiClient.deactivateSupplier(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["suppliers"] }),
  });

  function beginEdit(supplier: Supplier) {
    setEditingId(supplier.id);
    form.reset(formFromSupplier(supplier));
    document.getElementById("add-supplier")?.scrollIntoView({ behavior: "smooth" });
  }

  const errors = form.formState.errors;

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
          Procurement profiles for evaluation, approval routing, contract monitoring, and later
          supplier recommendations. Unapproved suppliers are never treated as approved.
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
                <th scope="col">Supplier ID</th>
                <th scope="col">Company</th>
                <th scope="col">Category</th>
                <th scope="col">Risk</th>
                <th scope="col">Rating</th>
                <th scope="col">Approval</th>
                <th scope="col">Status</th>
                {canManage ? <th scope="col">Actions</th> : null}
              </tr>
            </thead>
            <tbody>
              {suppliersQuery.data.items.map((supplier) => (
                <tr key={supplier.id}>
                  <td>{supplier.supplier_number ?? "—"}</td>
                  <td>
                    <strong>{supplier.name}</strong>
                    <div>{supplier.code ?? supplier.country_code ?? ""}</div>
                  </td>
                  <td>{(supplier.supplier_category ?? "other").replaceAll("_", " ")}</td>
                  <td>{supplier.risk_level ?? "low"}</td>
                  <td>{supplier.supplier_rating ?? "—"}</td>
                  <td>
                    <span
                      className={`status-pill ${
                        supplier.approval_status === "approved"
                          ? "tone-success"
                          : supplier.approval_status === "pending"
                            ? "tone-warning"
                            : "tone-danger"
                      }`}
                    >
                      {supplier.approval_status}
                    </span>
                  </td>
                  <td>{supplier.status}</td>
                  {canManage ? (
                    <td className="button-row">
                      <button type="button" className="linkish" onClick={() => beginEdit(supplier)}>
                        Edit
                      </button>
                      {supplier.approval_status !== "approved" && supplier.status === "active" ? (
                        <button type="button" onClick={() => approveMutation.mutate(supplier.id)}>
                          Mark approved
                        </button>
                      ) : null}
                      {supplier.status === "active" ? (
                        <button type="button" onClick={() => deactivateMutation.mutate(supplier.id)}>
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
              id="add-supplier"
              className="mgmt-form"
              onSubmit={form.handleSubmit((values) => saveMutation.mutate(values))}
              noValidate
            >
              <h2>{editingId ? "Edit supplier" : "Add supplier"}</h2>
              <p className="section-hint">
                {editingId
                  ? "Supplier ID stays the same. Rating, risk, and lead time are available to later procurement recommendations."
                  : "Supplier ID is assigned automatically when you save."}
              </p>
              <div className="form-sections">
                <section className="form-section">
                  <h3>Basic information</h3>
                  <p className="section-hint">Legal identity and whether the supplier can be used.</p>
                  <div className="form-grid">
                    <label>
                      Company name
                      <input {...form.register("name")} />
                      <FieldError message={errors.name?.message} />
                    </label>
                    <label>
                      Supplier code
                      <input {...form.register("code")} />
                    </label>
                    <label>
                      Business registration number
                      <input {...form.register("business_registration_number")} />
                    </label>
                    <label>
                      Tax / VAT number
                      <input {...form.register("tax_number")} />
                    </label>
                    <label>
                      Website
                      <input {...form.register("website")} placeholder="https://" />
                    </label>
                    <label>
                      Country
                      <input {...form.register("country_code")} placeholder="LK" />
                    </label>
                    <label>
                      City
                      <input {...form.register("city")} />
                    </label>
                    <label>
                      Status
                      <select {...form.register("status")}>
                        <option value="active">Active</option>
                        <option value="inactive">Inactive</option>
                      </select>
                    </label>
                    <label className="span-2">
                      Address
                      <input {...form.register("address")} />
                    </label>
                  </div>
                </section>

                <section className="form-section">
                  <h3>Contacts</h3>
                  <p className="section-hint">People procurement and approvals can reach.</p>
                  <div className="form-grid">
                    <label>
                      Primary contact name
                      <input {...form.register("primary_contact_name")} />
                    </label>
                    <label>
                      Primary contact email
                      <input type="email" {...form.register("primary_contact_email")} />
                      <FieldError message={errors.primary_contact_email?.message} />
                    </label>
                    <label>
                      Primary contact phone
                      <input {...form.register("primary_contact_phone")} />
                    </label>
                    <label>
                      Secondary contact name
                      <input {...form.register("secondary_contact_name")} />
                    </label>
                    <label>
                      Secondary contact email
                      <input type="email" {...form.register("secondary_contact_email")} />
                      <FieldError message={errors.secondary_contact_email?.message} />
                    </label>
                    <label>
                      Secondary contact phone
                      <input {...form.register("secondary_contact_phone")} />
                    </label>
                  </div>
                </section>

                <section className="form-section">
                  <h3>Procurement</h3>
                  <p className="section-hint">What they supply and how orders are placed.</p>
                  <div className="form-grid">
                    <label>
                      Supplier category
                      <select {...form.register("supplier_category")}>
                        <option value="raw_materials">Raw materials</option>
                        <option value="manufacturing">Manufacturing</option>
                        <option value="logistics">Logistics</option>
                        <option value="it_services">IT services</option>
                        <option value="consulting">Consulting</option>
                        <option value="finance">Finance</option>
                        <option value="other">Other</option>
                      </select>
                    </label>
                    <label>
                      Preferred currency
                      <input {...form.register("preferred_currency")} maxLength={3} />
                      <FieldError message={errors.preferred_currency?.message} />
                    </label>
                    <label className="span-2">
                      Products / services offered
                      <input {...form.register("products_services")} />
                    </label>
                    <label>
                      Lead time (days)
                      <input type="number" min={0} step={1} {...form.register("lead_time_days")} />
                      <FieldError message={errors.lead_time_days?.message} />
                    </label>
                    <label>
                      Minimum order quantity
                      <input type="number" min={0} step="0.01" {...form.register("minimum_order_quantity")} />
                      <FieldError message={errors.minimum_order_quantity?.message} />
                    </label>
                    <label className="span-2">
                      Payment terms
                      <input {...form.register("payment_terms")} placeholder="Net 30" />
                    </label>
                  </div>
                </section>

                <section className="form-section">
                  <h3>Risk and compliance</h3>
                  <p className="section-hint">Used for risk-based selection and contract monitoring.</p>
                  <div className="form-grid">
                    <label>
                      Risk level
                      <select {...form.register("risk_level")}>
                        <option value="low">Low</option>
                        <option value="medium">Medium</option>
                        <option value="high">High</option>
                      </select>
                    </label>
                    <label>
                      Compliance status
                      <select {...form.register("compliance_status")}>
                        <option value="pending">Pending</option>
                        <option value="compliant">Compliant</option>
                        <option value="non_compliant">Non-compliant</option>
                        <option value="expired">Expired</option>
                      </select>
                    </label>
                    <label>
                      Contract start date
                      <input type="date" {...form.register("contract_start_date")} />
                    </label>
                    <label>
                      Contract expiry date
                      <input type="date" {...form.register("contract_expiry_date")} />
                      <FieldError message={errors.contract_expiry_date?.message} />
                    </label>
                    <label className="checkbox-row">
                      <input type="checkbox" {...form.register("insurance_valid")} />
                      Insurance valid
                    </label>
                    <label className="span-2">
                      Certification details
                      <input {...form.register("certification_details")} />
                    </label>
                  </div>
                </section>

                <section className="form-section">
                  <h3>Performance</h3>
                  <p className="section-hint">Optional until order history is available.</p>
                  <div className="form-grid">
                    <label>
                      Supplier rating (1–5)
                      <input type="number" min={1} max={5} step="0.1" {...form.register("supplier_rating")} />
                      <FieldError message={errors.supplier_rating?.message} />
                    </label>
                    <label>
                      On-time delivery %
                      <input type="number" min={0} max={100} step="0.1" {...form.register("on_time_delivery_percent")} />
                      <FieldError message={errors.on_time_delivery_percent?.message} />
                    </label>
                    <label>
                      Quality score %
                      <input type="number" min={0} max={100} step="0.1" {...form.register("quality_score_percent")} />
                      <FieldError message={errors.quality_score_percent?.message} />
                    </label>
                    <label>
                      Average response time (hours)
                      <input type="number" min={0} step="0.1" {...form.register("average_response_hours")} />
                      <FieldError message={errors.average_response_hours?.message} />
                    </label>
                    <label>
                      Rejected orders
                      <input type="number" min={0} step={1} {...form.register("rejected_orders_count")} />
                      <FieldError message={errors.rejected_orders_count?.message} />
                    </label>
                    <label>
                      Total orders completed
                      <input type="number" min={0} step={1} {...form.register("total_orders_completed")} />
                      <FieldError message={errors.total_orders_completed?.message} />
                    </label>
                  </div>
                </section>

                <section className="form-section">
                  <h3>Approval and governance</h3>
                  <p className="section-hint">Controls who may use this supplier in a process.</p>
                  <div className="form-grid">
                    <label>
                      Approval status
                      <select {...form.register("approval_status")}>
                        <option value="pending">Pending</option>
                        <option value="approved">Approved</option>
                        <option value="rejected">Rejected</option>
                        <option value="suspended">Suspended</option>
                      </select>
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
                      <input type="checkbox" {...form.register("preferred_supplier")} />
                      Preferred supplier
                    </label>
                    <label className="checkbox-row">
                      <input type="checkbox" {...form.register("blacklisted")} />
                      Blacklisted
                    </label>
                    <label className="span-2">
                      Suspension reason
                      <input {...form.register("suspension_reason")} />
                    </label>
                    <label className="span-2">
                      Notes
                      <textarea rows={3} {...form.register("notes")} />
                    </label>
                  </div>
                </section>
              </div>

              <div className="page-header-actions">
                <button type="submit" disabled={saveMutation.isPending}>
                  {saveMutation.isPending ? "Saving…" : editingId ? "Save changes" : "Create supplier"}
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
              {(contactsQuery.data?.items ?? []).map((contact) => (
                <li key={contact.id}>
                  {contact.full_name} — {contact.email ?? "no email"} ({contact.status})
                </li>
              ))}
            </ul>
          </article>
          <article>
            <h2>Products</h2>
            <ul className="simple-list">
              {(productsQuery.data?.items ?? []).map((product) => (
                <li key={product.id}>
                  {product.name} {product.sku ? `(${product.sku})` : ""} — {product.unit_price ?? "—"}{" "}
                  {product.currency_code}
                </li>
              ))}
            </ul>
          </article>
        </div>
      </section>
    </RequirePermission>
  );
}
