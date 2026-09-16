import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { EmptyState } from "../../components/ui/EmptyState";
import { LoadingState } from "../../components/ui/LoadingState";
import { RequirePermission } from "../../components/RouteGuards";
import { apiClient } from "../../lib/apiClient";
import { PERMISSIONS } from "../../lib/permissions";
import { useOrganization } from "../../providers/OrganizationProvider";

const COMPARISON_FEATURES: { code: string; label: string }[] = [
  { code: "organization.max_users", label: "Max users" },
  { code: "organization.max_suppliers", label: "Max suppliers" },
  { code: "process.monthly_runs", label: "Monthly workflow runs" },
  { code: "documents.max_file_size", label: "Max upload size (bytes)" },
  { code: "agents.max_concurrent_runs", label: "Concurrent agent runs" },
  { code: "security.audit_retention_days", label: "Audit retention (days)" },
  { code: "integrations.email_enabled", label: "Email integration" },
  { code: "integrations.supplier_quotes_enabled", label: "Supplier quotes" },
  { code: "security.sso_enabled", label: "SSO / SAML" },
  { code: "security.scim_enabled", label: "SCIM" },
  { code: "analytics.advanced_enabled", label: "Advanced analytics" },
  { code: "audit.export_enabled", label: "Advanced audit export" },
  { code: "workers.dedicated_capacity", label: "Dedicated workers" },
  { code: "support.premium", label: "Premium support" },
];

function formatEntitlement(
  plans: Awaited<ReturnType<typeof apiClient.listBillingPlans>>["plans"],
  planCode: string,
  featureCode: string,
): string {
  const plan = plans.find((p) => p.plan_code === planCode);
  const row = plan?.entitlements.find((e) => e.feature_code === featureCode);
  if (!row) return "—";
  if (row.boolean_value != null) return row.boolean_value ? "Yes" : "No";
  if (row.numeric_limit != null) return String(row.numeric_limit);
  if (row.text_value) return row.text_value;
  return "—";
}

export function BillingPage() {
  const { activeOrganization, refetch } = useOrganization();
  const queryClient = useQueryClient();

  const plansQuery = useQuery({
    queryKey: ["billing", "plans"],
    queryFn: () => apiClient.listBillingPlans(),
  });

  const subscriptionQuery = useQuery({
    queryKey: ["billing", "subscription", activeOrganization?.id],
    queryFn: () => apiClient.getBillingSubscription(),
    enabled: Boolean(activeOrganization?.id),
  });

  const usageQuery = useQuery({
    queryKey: ["billing", "usage", activeOrganization?.id],
    queryFn: () => apiClient.getBillingUsage(),
    enabled: Boolean(activeOrganization?.id),
  });

  const upgradeMutation = useMutation({
    mutationFn: (plan_code: string) => apiClient.upgradePlan(plan_code),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["billing"] });
      refetch();
    },
  });

  const downgradeMutation = useMutation({
    mutationFn: (plan_code: string) => apiClient.downgradePlan(plan_code),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["billing"] });
      refetch();
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => apiClient.cancelSubscription(true),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["billing"] });
      refetch();
    },
  });

  const currentPlan = subscriptionQuery.data?.plan_code ?? activeOrganization?.plan_code;
  const plans = plansQuery.data?.plans ?? [];

  return (
    <RequirePermission
      permission={PERMISSIONS.BILLING_MANAGE}
      fallback={
        <EmptyState title="Access restricted" description="Billing is limited to owners/admins." />
      }
    >
      <section className="billing-admin">
        <h1>Billing administration</h1>
        <p className="lede">
          Server-side entitlements are authoritative. This UI may hide unavailable features, but
          the API enforces every limit.
        </p>

        {subscriptionQuery.isLoading || plansQuery.isLoading ? (
          <LoadingState label="Loading subscription…" />
        ) : (
          <>
            <dl className="status-grid">
              <div>
                <dt>Current plan</dt>
                <dd>{currentPlan}</dd>
              </div>
              <div>
                <dt>Subscription status</dt>
                <dd>{subscriptionQuery.data?.subscription?.status ?? "active"}</dd>
              </div>
              <div>
                <dt>Cancel at period end</dt>
                <dd>
                  {subscriptionQuery.data?.subscription?.cancel_at_period_end ? "Yes" : "No"}
                </dd>
              </div>
            </dl>

            <h2>Usage this period</h2>
            {usageQuery.isLoading ? (
              <LoadingState label="Loading usage…" />
            ) : (
              <ul className="usage-list">
                {Object.entries(usageQuery.data?.period_usage ?? {}).length === 0 ? (
                  <li>No metered usage recorded yet.</li>
                ) : (
                  Object.entries(usageQuery.data?.period_usage ?? {}).map(([meter, qty]) => (
                    <li key={meter}>
                      <strong>{meter}</strong>: {qty}
                      {usageQuery.data?.limits?.[meter] != null
                        ? ` / ${usageQuery.data.limits[meter]}`
                        : ""}
                    </li>
                  ))
                )}
              </ul>
            )}

            <h2>Plan comparison</h2>
            <div className="plan-compare">
              {plans.map((plan) => (
                <article key={plan.plan_code} className="plan-card">
                  <h3>{plan.display_name}</h3>
                  <p>{plan.description}</p>
                  <ul>
                    {plan.highlights.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                  {plan.plan_code === currentPlan ? (
                    <p className="plan-current">Current plan</p>
                  ) : (
                    <div className="plan-actions">
                      {["pro", "enterprise", "pro_max"].indexOf(plan.plan_code) >
                      ["pro", "enterprise", "pro_max"].indexOf(currentPlan ?? "pro") ? (
                        <button
                          type="button"
                          onClick={() => upgradeMutation.mutate(plan.plan_code)}
                          disabled={upgradeMutation.isPending}
                        >
                          Upgrade to {plan.display_name}
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => downgradeMutation.mutate(plan.plan_code)}
                          disabled={downgradeMutation.isPending}
                        >
                          Downgrade to {plan.display_name}
                        </button>
                      )}
                    </div>
                  )}
                </article>
              ))}
            </div>

            <div className="table-wrap">
              <table className="comparison-table">
                <thead>
                  <tr>
                    <th>Feature</th>
                    {plans.map((p) => (
                      <th key={p.plan_code}>{p.display_name}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {COMPARISON_FEATURES.map((feature) => (
                    <tr key={feature.code}>
                      <td>{feature.label}</td>
                      {plans.map((p) => (
                        <td key={p.plan_code}>
                          {formatEntitlement(plans, p.plan_code, feature.code)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <h2>Cancel subscription</h2>
            <p>Cancellation at period end keeps current entitlements until the billing period ends.</p>
            <button
              type="button"
              onClick={() => cancelMutation.mutate()}
              disabled={cancelMutation.isPending}
            >
              Cancel at period end
            </button>
          </>
        )}
      </section>
    </RequirePermission>
  );
}
