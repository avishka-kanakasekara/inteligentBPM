import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApprovalBadge, RiskBadge } from "../../components/process/StatusBadges";
import { EmptyState } from "../../components/ui/EmptyState";
import { LoadingState } from "../../components/ui/LoadingState";
import { PageHeader } from "../../components/ui/PageHeader";
import { RetryState } from "../../components/ui/RetryState";
import { RequirePermission } from "../../components/RouteGuards";
import { ApiError, apiClient } from "../../lib/apiClient";
import { PERMISSIONS } from "../../lib/permissions";
import { useOrganization } from "../../providers/OrganizationProvider";

export function ApprovalsPage() {
  const { activeOrganization } = useOrganization();
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["approvals", activeOrganization?.id],
    queryFn: () => apiClient.listApprovals(),
    enabled: Boolean(activeOrganization?.id),
  });

  const decideMutation = useMutation({
    mutationFn: async ({
      approvalId,
      decision,
    }: {
      approvalId: string;
      decision: "approved" | "rejected";
    }) => {
      const current = await apiClient.getApproval(approvalId);
      return apiClient.decideApproval(approvalId, {
        decision,
        note: decision === "approved" ? "Approved from approval center" : "Rejected from approval center",
        row_version: current.row_version,
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["approvals"] });
      void queryClient.invalidateQueries({ queryKey: ["processes"] });
    },
    onError: (err: unknown) => {
      const message =
        err instanceof ApiError
          ? `${err.message}${err.code ? ` (${err.code})` : ""}`
          : err instanceof Error
            ? err.message
            : "Decision failed";
      alert(message);
    },
  });

  const items = query.data ?? [];
  const pendingCount = items.filter((item) => item.status === "pending").length;

  return (
    <RequirePermission
      permission={PERMISSIONS.APPROVALS_READ}
      fallback={
        <EmptyState title="Access restricted" description="Approval center is not available." />
      }
    >
      <section>
        <PageHeader
          eyebrow="Governance"
          title="Risk and approval center"
          description="Deterministic risk decisions with policy evidence. Approvals bind exact plan and risk snapshot hashes."
          actions={<span className="status-pill tone-warning">{pendingCount} pending</span>}
        />
        {query.isLoading ? <LoadingState label="Loading approvals…" /> : null}
        {query.isError ? (
          <RetryState message={query.error.message} onRetry={() => void query.refetch()} />
        ) : null}
        {!query.isLoading && !query.isError && items.length === 0 ? (
          <EmptyState title="No approvals" description="Nothing is waiting for a decision." />
        ) : null}
        <ul className="approval-list">
          {items.map((item) => (
            <li key={item.id} className="approval-item risk-approval-card">
              <div className="badge-row">
                <strong>{item.process_name || "Unknown process"}</strong>
                <ApprovalBadge status={item.status} />
                <RiskBadge level={item.risk_level} />
                {item.risk_decision ? (
                  <span className="status-pill" data-decision={item.risk_decision}>
                    Decision: {item.risk_decision}
                  </span>
                ) : null}
              </div>

              <section className="risk-section" aria-labelledby={`risk-summary-${item.id}`}>
                <h2 id={`risk-summary-${item.id}`}>Risk summary</h2>
                <p>{item.risk_summary ?? "Risk analysis pending or unavailable."}</p>
              </section>

              <section className="risk-section" aria-labelledby={`policy-evidence-${item.id}`}>
                <h2 id={`policy-evidence-${item.id}`}>Policy evidence</h2>
                {(item.policy_evidence?.length ?? 0) === 0 ? (
                  <p>No policy evidence attached.</p>
                ) : (
                  <ul className="check-list">
                    {item.policy_evidence.map((ev) => (
                      <li key={ev}>{ev}</li>
                    ))}
                  </ul>
                )}
                <p>
                  Sources:{" "}
                  {(item.source_refs ?? []).map((ref) => ref.label).join("; ") || "None"}
                </p>
              </section>

              <section className="risk-section" aria-labelledby={`risk-detail-${item.id}`}>
                <h2 id={`risk-detail-${item.id}`}>Risk detail</h2>
                {(item.risk_items?.length ?? 0) === 0 ? (
                  <p>No detailed risk items.</p>
                ) : (
                  <ul className="risk-item-list">
                    {item.risk_items?.map((risk) => (
                      <li key={risk.id}>
                        <strong>
                          {risk.category} · {risk.severity}
                          {risk.blocking ? " · blocking" : ""}
                        </strong>
                        <p>{risk.description}</p>
                        <p>Remediation: {risk.required_remediation}</p>
                        {risk.policy_code ? <p>Policy: {risk.policy_code}</p> : null}
                        {risk.required_approver ? (
                          <p>Approver: {risk.required_approver}</p>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section className="risk-section" aria-labelledby={`required-approvals-${item.id}`}>
                <h2 id={`required-approvals-${item.id}`}>Required approvals</h2>
                <p>Required roles: {(item.required_roles ?? []).join(", ") || "None"}</p>
                <p>
                  Plan hash: {item.plan_snapshot_hash ?? "n/a"} · Risk hash:{" "}
                  {item.risk_snapshot_hash ?? item.snapshot_hash}
                </p>
                {item.process_id ? (
                  <p className="muted tight">Process ID: {item.process_id}</p>
                ) : null}
                {item.override_required ? (
                  <p className="blocked-callout">
                    Override workflow required — prohibited actions need audited authorization.
                  </p>
                ) : null}
              </section>

              <section className="risk-section" aria-labelledby={`approval-history-${item.id}`}>
                <h2 id={`approval-history-${item.id}`}>Approval history</h2>
                {(item.approval_history?.length ?? 0) === 0 ? (
                  <p>Human decision: {item.decision_note ?? "Pending"}</p>
                ) : (
                  <ul className="check-list">
                    {item.approval_history?.map((event, idx) => (
                      <li key={`${item.id}-hist-${idx}`}>
                        {event.action}
                        {event.actor ? ` · ${event.actor}` : ""}
                        {event.note ? ` — ${event.note}` : ""}
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {item.risk_decision === "BLOCKED" || item.blocking_explanation ? (
                <section
                  className="risk-section blocked-process"
                  aria-labelledby={`blocked-${item.id}`}
                >
                  <h2 id={`blocked-${item.id}`}>Blocked process explanation</h2>
                  <p>
                    {item.blocking_explanation ??
                      "This process is blocked by deterministic policy rules and cannot proceed without an audited override."}
                  </p>
                </section>
              ) : null}

              {item.status === "pending" ? (
                <div className="plan-actions">
                  <button
                    type="button"
                    disabled={decideMutation.isPending}
                    onClick={() =>
                      void decideMutation.mutate({ approvalId: item.id, decision: "approved" })
                    }
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    className="btn-danger"
                    disabled={decideMutation.isPending}
                    onClick={() =>
                      void decideMutation.mutate({ approvalId: item.id, decision: "rejected" })
                    }
                  >
                    Reject
                  </button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
    </RequirePermission>
  );
}
