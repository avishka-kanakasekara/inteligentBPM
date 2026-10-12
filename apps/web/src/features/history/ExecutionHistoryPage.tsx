import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ProcessStatusCard } from "../../components/process/ProcessStatusCard";
import { ProcessStatusBadge } from "../../components/process/StatusBadges";
import { EmptyState } from "../../components/ui/EmptyState";
import { LoadingState } from "../../components/ui/LoadingState";
import { PageHeader } from "../../components/ui/PageHeader";
import { RetryState } from "../../components/ui/RetryState";
import { apiClient } from "../../lib/apiClient";
import { useOrganization } from "../../providers/OrganizationProvider";
import { isProcessStatus, selectHistoryEntries } from "./historyEntries";

function formatWhen(value?: string | null) {
  if (!value) return "—";
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

export function ExecutionHistoryPage() {
  const { activeOrganization } = useOrganization();
  const [openKey, setOpenKey] = useState<string | null>(null);
  const enabled = Boolean(activeOrganization?.id);

  const processesQuery = useQuery({
    queryKey: ["history", "processes", activeOrganization?.id],
    queryFn: () => apiClient.listProcesses(),
    enabled,
  });
  const runsQuery = useQuery({
    queryKey: ["history", "process-runs", activeOrganization?.id],
    queryFn: () => apiClient.listProcessRuns({ limit: 100 }),
    enabled,
  });

  if (!enabled || processesQuery.isPending || runsQuery.isPending) {
    return <LoadingState label="Loading history…" />;
  }

  if (processesQuery.isError || runsQuery.isError) {
    const message =
      (processesQuery.error as Error | null)?.message ||
      (runsQuery.error as Error | null)?.message ||
      "Could not load execution history.";
    return (
      <RetryState
        title="History unavailable"
        message={message}
        onRetry={() => {
          void processesQuery.refetch();
          void runsQuery.refetch();
        }}
      />
    );
  }

  const history = selectHistoryEntries(processesQuery.data ?? [], runsQuery.data?.items ?? []);

  return (
    <section>
      <PageHeader
        eyebrow="Traceability"
        title="Execution history"
        description="Completed, cancelled, failed, and rejected runs, with the human decision recorded on each process."
      />
      {history.length === 0 ? (
        <EmptyState
          title="No historical runs"
          description="Finished and cancelled runs will be listed here after execution ends."
        />
      ) : (
        <div className="card-stack">
          {history.map((entry) => {
            const open = openKey === entry.key;
            return (
              <article key={entry.key} className="runs-item process-card">
                <div className="runs-item-head">
                  <div>
                    <h2>{entry.title}</h2>
                    <p className="muted tight">
                      {formatWhen(entry.when)}
                      {entry.run ? ` · Run ${entry.run.id.slice(0, 8)}` : " · No process run"}
                    </p>
                  </div>
                  {isProcessStatus(entry.status) ? (
                    <ProcessStatusBadge status={entry.status} />
                  ) : (
                    <span className="status-pill">{entry.status}</span>
                  )}
                </div>
                <dl className="process-meta">
                  <div>
                    <dt>Human decision</dt>
                    <dd>{entry.humanDecision ?? "None recorded"}</dd>
                  </div>
                  {entry.note ? (
                    <div>
                      <dt>Note</dt>
                      <dd>{entry.note}</dd>
                    </div>
                  ) : null}
                </dl>
                {entry.process ? (
                  <div className="runs-item-actions">
                    <button
                      type="button"
                      className="btn ghost-btn"
                      aria-expanded={open}
                      onClick={() => setOpenKey(open ? null : entry.key)}
                    >
                      {open ? "Hide outcome" : "Show outcome"}
                    </button>
                  </div>
                ) : null}
                {open && entry.process ? (
                  <ProcessStatusCard process={entry.process} readOnly />
                ) : null}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
