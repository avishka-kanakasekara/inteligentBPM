import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ProcessStatusBadge, RiskBadge } from "../../components/process/StatusBadges";
import { LoadingState } from "../../components/ui/LoadingState";
import { PageHeader } from "../../components/ui/PageHeader";
import { RetryState } from "../../components/ui/RetryState";
import { apiClient } from "../../lib/apiClient";
import { useOrganization } from "../../providers/OrganizationProvider";

export function DashboardPage() {
  const { activeOrganization } = useOrganization();
  const query = useQuery({
    queryKey: ["processes", activeOrganization?.id],
    queryFn: () => apiClient.listProcesses(),
    enabled: Boolean(activeOrganization),
  });

  const processes = query.data ?? [];
  const metrics = useMemo(() => {
    const activeRuns = processes.filter((p) => ["executing", "paused"].includes(p.status)).length;
    const pendingApprovals = processes.filter((p) => p.status === "awaiting_approval").length;
    const completed = processes.filter((p) => p.status === "completed").length;
    const blocked = processes.filter((p) => p.status === "blocked" || p.status === "failed").length;
    return { activeRuns, pendingApprovals, completed, blocked };
  }, [processes]);

  const attention = processes.filter((p) =>
    ["awaiting_approval", "blocked", "failed", "paused"].includes(p.status),
  );
  const recent = [...processes].slice(0, 6);

  if (query.isLoading) return <LoadingState label="Loading dashboard…" />;
  if (query.isError) {
    return (
      <RetryState
        message={query.error.message}
        onRetry={() => void query.refetch()}
      />
    );
  }

  return (
    <section>
      <PageHeader
        eyebrow="Operations"
        title="Dashboard"
        description={`Live view of process state, risk, approvals, and execution for ${activeOrganization?.name}.`}
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
          <p className="kpi-hint">Executing or paused</p>
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
          <p className="kpi-hint">Needs attention</p>
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
                      <ProcessStatusBadge status={process.status} />
                      <RiskBadge level={process.risk_level} />
                    </div>
                  </div>
                  <Link to={process.status === "awaiting_approval" ? "/approvals" : "/runs"} className="linkish">
                    {process.status === "awaiting_approval" ? "Review approval" : "Open run"}
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
                          <ProcessStatusBadge status={process.status} />
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
                    <ProcessStatusBadge status={process.status} />
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
