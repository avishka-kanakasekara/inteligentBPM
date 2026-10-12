import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ProcessActivity } from "../../components/process/ProcessActivity";
import { RiskBadge } from "../../components/process/StatusBadges";
import { LoadingState } from "../../components/ui/LoadingState";
import { PageHeader } from "../../components/ui/PageHeader";
import { RetryState } from "../../components/ui/RetryState";
import { apiClient } from "../../lib/apiClient";
import { organizationDisplayName } from "../../lib/organizationDisplay";
import { useOrganization } from "../../providers/OrganizationProvider";
import { selectDashboardMetrics } from "./dashboardMetrics";

export function DashboardPage() {
  const { activeOrganization } = useOrganization();
  const enabled = Boolean(activeOrganization?.id);

  const processesQuery = useQuery({
    queryKey: ["processes", activeOrganization?.id],
    queryFn: () => apiClient.listProcesses(),
    enabled,
  });
  const runsQuery = useQuery({
    queryKey: ["dashboard", "process-runs", activeOrganization?.id],
    queryFn: () => apiClient.listProcessRuns({ limit: 100 }),
    enabled,
  });
  const approvalsQuery = useQuery({
    queryKey: ["dashboard", "approvals", activeOrganization?.id],
    queryFn: () => apiClient.listApprovals(),
    enabled,
  });

  const processes = processesQuery.data ?? [];
  const metrics = useMemo(
    () =>
      selectDashboardMetrics(
        processes,
        runsQuery.data?.items ?? [],
        approvalsQuery.data ?? [],
      ),
    [approvalsQuery.data, processes, runsQuery.data],
  );
  const attentionIds = new Set([...metrics.blockedProcessIds, ...metrics.pendingProcessIds]);
  const attention = processes.filter((process) => attentionIds.has(process.id));
  const recent = [...processes].slice(0, 6);
  const failed =
    !enabled || processesQuery.isPending || runsQuery.isPending || approvalsQuery.isPending
      ? null
      : processesQuery.isError || runsQuery.isError || approvalsQuery.isError;

  if (!enabled || processesQuery.isPending || runsQuery.isPending || approvalsQuery.isPending) {
    return <LoadingState label="Loading dashboard…" />;
  }
  if (failed) {
    const message =
      (processesQuery.error as Error | null)?.message ||
      (runsQuery.error as Error | null)?.message ||
      (approvalsQuery.error as Error | null)?.message ||
      "Could not load the dashboard.";
    return (
      <RetryState
        message={message}
        onRetry={() => {
          void processesQuery.refetch();
          void runsQuery.refetch();
          void approvalsQuery.refetch();
        }}
      />
    );
  }

  return (
    <section>
      <PageHeader
        eyebrow="Operations"
        title="Dashboard"
        description={`Live view of process state, risk, approvals, and execution for ${
          activeOrganization ? organizationDisplayName(activeOrganization) : "this workspace"
        }.`}
        actions={
          <Link to="/discovery" className="btn btn-primary">
            Start discovery
          </Link>
        }
      />

      <dl className="kpi-band" style={{ marginBottom: "1.25rem" }}>
        <div>
          <dt className="kpi-label">Total processes</dt>
          <dd className="kpi-value">{processes.length}</dd>
          <p className="kpi-hint">Across the active workspace</p>
        </div>
        <div>
          <dt className="kpi-label">Active runs</dt>
          <dd className="kpi-value">{metrics.activeRuns}</dd>
          <p className="kpi-hint">Open runs</p>
        </div>
        <div>
          <dt className="kpi-label">Pending approvals</dt>
          <dd className="kpi-value">{metrics.pendingApprovals}</dd>
          <p className="kpi-hint">Awaiting decision</p>
        </div>
        <div>
          <dt className="kpi-label">Completed</dt>
          <dd className="kpi-value">{metrics.completed}</dd>
          <p className="kpi-hint">Finished executions</p>
        </div>
        <div>
          <dt className="kpi-label">Blocked</dt>
          <dd className="kpi-value">{metrics.blocked}</dd>
          <p className="kpi-hint">Risk blocked or failed</p>
        </div>
      </dl>

      <div className="ops-grid">
        <div className="ops-panel">
          <h2>Process health</h2>
          <p className="lede">
            {attention.length > 0
              ? `${attention.length} item${attention.length === 1 ? "" : "s"} need review before work can continue.`
              : "No blocked or approval-required items right now."}
          </p>

          {attention.length > 0 ? (
            <ul className="attention-list">
              {attention.slice(0, 8).map((process) => (
                <li key={process.id}>
                  <div>
                    <strong>{process.name}</strong>
                    <div className="badge-row" style={{ marginTop: "0.35rem" }}>
                      <ProcessActivity process={process} />
                      <RiskBadge level={process.risk_level} />
                    </div>
                  </div>
                  <Link
                    to={metrics.pendingProcessIds.includes(process.id) ? "/approvals" : "/runs"}
                    className="linkish"
                  >
                    {metrics.pendingProcessIds.includes(process.id) ? "Review approval" : "Open run"}
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Process</th>
                    <th scope="col">Status</th>
                    <th scope="col">Risk</th>
                  </tr>
                </thead>
                <tbody>
                  {recent.length === 0 ? (
                    <tr>
                      <td colSpan={3}>No processes yet. Start discovery to create one.</td>
                    </tr>
                  ) : (
                    recent.map((process) => (
                      <tr key={process.id}>
                        <td>{process.name}</td>
                        <td>
                          <ProcessActivity process={process} />
                        </td>
                        <td>
                          <RiskBadge level={process.risk_level} />
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div style={{ display: "grid", gap: "1rem" }}>
          <div className="ops-panel">
            <h2>Quick actions</h2>
            <div className="action-stack" style={{ marginTop: "0.85rem" }}>
              <Link to="/discovery">
                Start discovery
                <span className="action-meta">Create process</span>
              </Link>
              <Link to="/approvals">
                Review approvals
                <span className="action-meta">{metrics.pendingApprovals} pending</span>
              </Link>
              <Link to="/runs">
                Open active runs
                <span className="action-meta">{metrics.activeRuns} live</span>
              </Link>
            </div>
          </div>

          <div className="ops-panel">
            <h2>Recent processes</h2>
            <ul className="activity-list" style={{ marginTop: "0.85rem" }}>
              {recent.length === 0 ? (
                <li>
                  <span className="muted">No recent activity</span>
                </li>
              ) : (
                recent.slice(0, 5).map((process) => (
                  <li key={process.id}>
                    <span>{process.name}</span>
                    <ProcessActivity process={process} />
                  </li>
                ))
              )}
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}
