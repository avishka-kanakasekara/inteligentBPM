import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { EmptyState } from "../../components/ui/EmptyState";
import { LoadingState } from "../../components/ui/LoadingState";
import { PageHeader } from "../../components/ui/PageHeader";
import { RetryState } from "../../components/ui/RetryState";
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

const PLAN_ORDER = ["pro", "enterprise", "pro_max"] as const;

function formatEntitlement(
  plans: Awaited<ReturnType<typeof apiClient.listBillingPlans>>["plans"],
  planCode: string,
  featureCode: string,
): string {
  const plan = plans.find((p) => p.plan_code === planCode);
  const row = plan?.entitlements.find((e) => e.feature_code === featureCode);
  if (!row) return "—";
  if (row.boolean_value != null) return row.boolean_value ? "Yes" : "No";
  if (row.numeric_limit != null) return Number(row.numeric_limit).toLocaleString();
  if (row.text_value) return row.text_value;
  return "—";
}

function usagePercent(used: number, limit: number | null | undefined) {
  if (limit == null || limit <= 0) return null;
  return Math.min(100, Math.round((used / limit) * 100));
}

function planRank(code: string | undefined) {
  const idx = PLAN_ORDER.indexOf((code as (typeof PLAN_ORDER)[number]) ?? "pro");
  return idx < 0 ? 0 : idx;
}

export function BillingPage() {
  const { activeOrganization, refetch } = useOrganization();
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<string | null>(null);

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

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ["billing"] });
    refetch();
  };

  const upgradeMutation = useMutation({
    mutationFn: (plan_code: string) => apiClient.upgradePlan(plan_code),
    onSuccess: async (_, plan) => {
      await invalidate();
      setNotice(`Upgraded to ${plan}. Entitlements refresh on the next request.`);
    },
  });

  const downgradeMutation = useMutation({
    mutationFn: (plan_code: string) => apiClient.downgradePlan(plan_code),
    onSuccess: async (_, plan) => {
      await invalidate();
      setNotice(`Downgraded to ${plan}. Limits apply immediately on the server.`);
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => apiClient.cancelSubscription(true),
    onSuccess: async () => {
      await invalidate();
      setNotice("Cancellation scheduled at period end.");
    },
  });

  const currentPlan = subscriptionQuery.data?.plan_code ?? activeOrganization?.plan_code;
  const plans = useMemo(
    () => [...(plansQuery.data?.plans ?? [])].sort((a, b) => a.sort_order - b.sort_order),
    [plansQuery.data],
  );
  const usageEntries = Object.entries(usageQuery.data?.period_usage ?? {});
  const busy =
    upgradeMutation.isPending || downgradeMutation.isPending || cancelMutation.isPending;

  const isLoading =
    subscriptionQuery.isLoading || plansQuery.isLoading || usageQuery.isLoading;
  const isError = subscriptionQuery.isError || plansQuery.isError || usageQuery.isError;

  return (
    <RequirePermission
      permission={PERMISSIONS.BILLING_MANAGE}
      fallback={
        <EmptyState title="Access restricted" description="Billing is limited to owners/admins." />
      }
    >
      <section className="billing-page">
        <PageHeader
          eyebrow="Administration"
          title="Billing & plans"
          description="Server-side entitlements are authoritative. This page can hide unavailable features, but the API enforces every limit."
        />

        {isLoading ? (
          <LoadingState label="Loading subscription…" />
        ) : isError ? (
          <RetryState
            title="Could not load billing"
            message={
              (subscriptionQuery.error as Error | null)?.message ||
              (plansQuery.error as Error | null)?.message ||
              "Check your connection and try again."
            }
            onRetry={() => {
              void plansQuery.refetch();
              void subscriptionQuery.refetch();
              void usageQuery.refetch();
            }}
          />
        ) : (
          <>
            {notice ? (
              <p className="inline-notice" role="status">
                {notice}
              </p>
            ) : null}

            <div className="billing-hero">
              <div>
                <p className="eyebrow">Current subscription</p>
                <h2>{plans.find((p) => p.plan_code === currentPlan)?.display_name ?? currentPlan}</h2>
                <p className="lede" style={{ marginBottom: 0 }}>
                  {activeOrganization?.name} · status{" "}
                  <strong>{subscriptionQuery.data?.subscription?.status ?? "active"}</strong>
                  {subscriptionQuery.data?.subscription?.cancel_at_period_end
                    ? " · cancels at period end"
                    : ""}
                </p>
              </div>
              <div className="billing-hero-meta">
                <div>
                  <span className="kpi-label">Plan code</span>
                  <strong>{currentPlan}</strong>
                </div>
                <div>
                  <span className="kpi-label">Organization</span>
                  <strong>{activeOrganization?.slug ?? "—"}</strong>
                </div>
                <Link to="/settings" className="ghost-btn">
                  Workspace settings
                </Link>
              </div>
            </div>

            <div className="ops-panel" style={{ marginBottom: "1.25rem" }}>
              <h2>Usage this period</h2>
              <p className="lede">Metered consumption against plan limits for the active org.</p>
              {usageEntries.length === 0 ? (
                <EmptyState title="No metered usage yet" description="Workflow runs and related meters will appear here." />
              ) : (
                <ul className="usage-list">
                  {usageEntries.map(([meter, qty]) => {
                    const limit = usageQuery.data?.limits?.[meter];
                    const pct = usagePercent(qty, limit);
                    return (
                      <li key={meter}>
                        <div className="usage-row">
                          <strong>{meter}</strong>
                          <span>
                            {qty.toLocaleString()}
                            {limit != null ? ` / ${limit.toLocaleString()}` : ""}
                          </span>
                        </div>
                        {pct != null ? (
                          <div className="usage-meter" aria-hidden="true">
                            <span style={{ width: `${pct}%` }} />
                          </div>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>

            <h2 className="section-title">Choose a plan</h2>
            <div className="plan-compare">
              {plans.map((plan) => {
                const isCurrent = plan.plan_code === currentPlan;
                const higher = planRank(plan.plan_code) > planRank(currentPlan);
                return (
                  <article
                    key={plan.plan_code}
                    className={`plan-card ${isCurrent ? "is-current" : ""}`}
                  >
                    <div className="plan-card-head">
                      <h3>{plan.display_name}</h3>
                      {isCurrent ? <span className="status-pill tone-success">Current</span> : null}
                    </div>
                    <p className="card-summary">{plan.description}</p>
                    <ul className="plan-highlights">
                      {plan.highlights.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                    {isCurrent ? (
                      <p className="plan-current">You are on this plan</p>
                    ) : (
                      <div className="plan-actions">
                        <button
                          type="button"
                          className={higher ? "btn btn-primary" : "ghost-btn"}
                          onClick={() =>
                            higher
                              ? upgradeMutation.mutate(plan.plan_code)
                              : downgradeMutation.mutate(plan.plan_code)
                          }
                          disabled={busy}
                        >
                          {higher
                            ? `Upgrade to ${plan.display_name}`
                            : `Downgrade to ${plan.display_name}`}
                        </button>
                      </div>
                    )}
                  </article>
                );
              })}
            </div>

            <div className="ops-panel" style={{ marginTop: "1.25rem" }}>
              <h2>Feature comparison</h2>
              <p className="lede">Limits and feature flags resolved from the plan catalog.</p>
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
            </div>

            <div className="billing-danger">
              <div>
                <h2>Cancel subscription</h2>
                <p className="lede" style={{ marginBottom: 0 }}>
                  Cancellation at period end keeps current entitlements until the billing period closes.
                </p>
              </div>
              <button
                type="button"
                className="danger-btn"
                onClick={() => cancelMutation.mutate()}
                disabled={busy || Boolean(subscriptionQuery.data?.subscription?.cancel_at_period_end)}
              >
                {subscriptionQuery.data?.subscription?.cancel_at_period_end
                  ? "Cancellation scheduled"
                  : "Cancel at period end"}
              </button>
            </div>
          </>
        )}
      </section>
    </RequirePermission>
  );
}
