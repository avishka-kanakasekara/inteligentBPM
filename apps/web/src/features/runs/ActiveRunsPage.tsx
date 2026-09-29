import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ProcessRun, ProcessSummary } from "@bpm/frontend-types";
import { ProcessStatusCard } from "../../components/process/ProcessStatusCard";
import { ProcessStatusBadge } from "../../components/process/StatusBadges";
import { EmptyState } from "../../components/ui/EmptyState";
import { LoadingState } from "../../components/ui/LoadingState";
import { PageHeader } from "../../components/ui/PageHeader";
import { RetryState } from "../../components/ui/RetryState";
import { ApiError, apiClient } from "../../lib/apiClient";
import { useProcessRunEvents } from "../../hooks/useProcessRunEvents";
import { useOrganization } from "../../providers/OrganizationProvider";

const ACTIVE_PROCESS_STATUSES = new Set([
  "discovering",
  "plan_ready",
  "allocating",
  "allocated",
  "analyzing_risk",
  "risk_complete",
  "awaiting_approval",
  "approved",
  "executing",
  "paused",
  "blocked",
  "failed",
]);

const ACTIVE_RUN_STATUSES = new Set([
  "executing",
  "paused",
  "blocked",
  "awaiting_approval",
  "approved",
]);

const TERMINAL_STATUSES = new Set(["completed", "cancelled"]);

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

type ActiveItem = {
  process: ProcessSummary;
  run: ProcessRun | null;
};

export function ActiveRunsPage() {
  const { activeOrganization } = useOrganization();
  const queryClient = useQueryClient();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  const processesQuery = useQuery({
    queryKey: ["active-runs", "processes", activeOrganization?.id],
    queryFn: () => apiClient.listProcesses(),
    enabled: Boolean(activeOrganization?.id),
  });

  const runsQuery = useQuery({
    queryKey: ["active-runs", "process-runs", activeOrganization?.id],
    queryFn: () => apiClient.listProcessRuns({ limit: 100 }),
    enabled: Boolean(activeOrganization?.id),
    refetchInterval: 8_000,
  });

  const completeMutation = useMutation({
    mutationFn: (processId: string) => apiClient.completeProcess(processId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["active-runs"] }),
        queryClient.invalidateQueries({ queryKey: ["process-plans"] }),
        queryClient.invalidateQueries({ queryKey: ["processes"] }),
        queryClient.invalidateQueries({ queryKey: ["history"] }),
        queryClient.invalidateQueries({ queryKey: ["audit-events"] }),
      ]);
    },
  });

  const items = useMemo<ActiveItem[]>(() => {
    const processes = processesQuery.data ?? [];
    const runs = runsQuery.data?.items ?? [];
    const byProcess = new Map<string, ProcessRun>();
    for (const run of runs) {
      if (!ACTIVE_RUN_STATUSES.has(run.status)) continue;
      const existing = byProcess.get(run.process_id);
      if (
        !existing ||
        new Date(run.updated_at || run.created_at) >
          new Date(existing.updated_at || existing.created_at)
      ) {
        byProcess.set(run.process_id, run);
      }
    }

    const selected = new Map<string, ActiveItem>();
    for (const process of processes) {
      const run = byProcess.get(process.id) ?? null;
      if (run || ACTIVE_PROCESS_STATUSES.has(process.status)) {
        selected.set(process.id, { process, run });
      }
    }
    for (const [processId, run] of byProcess) {
      if (selected.has(processId)) continue;
      const process = processes.find((p) => p.id === processId);
      if (process) selected.set(processId, { process, run });
    }
    return Array.from(selected.values()).sort((a, b) => {
      const aTime = a.run?.updated_at || a.run?.created_at || a.process.updated_at;
      const bTime = b.run?.updated_at || b.run?.created_at || b.process.updated_at;
      return new Date(bTime).getTime() - new Date(aTime).getTime();
    });
  }, [processesQuery.data, runsQuery.data]);

  const activeRunId =
    selectedRunId && items.some((item) => item.run?.id === selectedRunId)
      ? selectedRunId
      : items.find((item) => item.run)?.run?.id ?? null;

  const { messages, status } = useProcessRunEvents(
    activeRunId,
    activeRunId ? apiClient.processRunEventsUrl(activeRunId) : null,
  );

  if (processesQuery.isLoading || runsQuery.isLoading) {
    return <LoadingState label="Loading active runs…" />;
  }

  if (processesQuery.isError || runsQuery.isError) {
    const message =
      (processesQuery.error as Error | null)?.message ||
      (runsQuery.error as Error | null)?.message ||
      "Could not load active runs.";
    return (
      <RetryState
        title="Active runs unavailable"
        message={message}
        onRetry={() => {
          void processesQuery.refetch();
          void runsQuery.refetch();
        }}
      />
    );
  }

  const executing = items.filter((i) => (i.run?.status || i.process.status) === "executing").length;
  const paused = items.filter((i) => (i.run?.status || i.process.status) === "paused").length;
  const blocked = items.filter((i) => ["blocked", "failed"].includes(i.run?.status || i.process.status)).length;
  const awaiting = items.filter((i) => ["awaiting_approval", "approved"].includes(i.process.status)).length;
  const completingId =
    completeMutation.isPending && typeof completeMutation.variables === "string"
      ? completeMutation.variables
      : null;

  function handleComplete(process: ProcessSummary) {
    if (TERMINAL_STATUSES.has(process.status)) return;
    if (
      !window.confirm(
        `Mark "${process.name}" as complete? This closes the process and any active runs.`,
      )
    ) {
      return;
    }
    completeMutation.mutate(process.id);
  }

  return (
    <section className="runs-page">
      <PageHeader
        eyebrow="Execution"
        title="Active process runs"
        description="Live execution status with stream updates where a process run exists."
        actions={
          <span className={`live-dot ${status === "open" ? "is-live" : ""}`} aria-live="polite">
            Stream: {activeRunId ? status : "idle"}
          </span>
        }
      />

      {completeMutation.isError ? (
        <p className="inline-notice is-error" role="alert">
          {completeMutation.error instanceof ApiError
            ? completeMutation.error.message
            : completeMutation.error.message}
        </p>
      ) : null}

      <dl className="kpi-band" style={{ marginBottom: "1.25rem" }}>
        <div>
          <dt className="kpi-label">In pipeline</dt>
          <dd className="kpi-value">{items.length}</dd>
          <p className="kpi-hint">All active processes</p>
        </div>
        <div>
          <dt className="kpi-label">Executing</dt>
          <dd className="kpi-value">{executing}</dd>
          <p className="kpi-hint">Gateway tools in flight</p>
        </div>
        <div>
          <dt className="kpi-label">Awaiting approval</dt>
          <dd className="kpi-value">{awaiting}</dd>
          <p className="kpi-hint">Pending human decision</p>
        </div>
        <div>
          <dt className="kpi-label">Paused / Blocked</dt>
          <dd className="kpi-value">{paused + blocked}</dd>
          <p className="kpi-hint">Needs attention</p>
        </div>
      </dl>

      {items.length === 0 ? (
        <EmptyState
          title="No active processes"
          description="Processes appear here after discovery completes. Start a new process from Discovery."
        />
      ) : (
        <div className="runs-layout">
          <div className="card-stack">
            {items.map(({ process, run }) => {
              const isTerminal = TERMINAL_STATUSES.has(process.status);
              const isCompleting = completingId === process.id;
              return (
                <article key={process.id} className="runs-item">
                  <div className="runs-item-head">
                    <div>
                      <h2>{process.name}</h2>
                      <p className="muted tight">
                        Updated {formatWhen(run?.updated_at || process.updated_at)}
                        {run ? ` · Run ${run.id.slice(0, 8)}` : " · No process run yet"}
                      </p>
                    </div>
                    <div className="badge-row">
                      <ProcessStatusBadge status={process.status} />
                      {run ? (
                        <span className="status-pill tone-info">run: {run.status}</span>
                      ) : null}
                      {isTerminal ? (
                        <span className="status-pill tone-success">Project complete</span>
                      ) : null}
                    </div>
                  </div>
                  {run?.pause_reason ? (
                    <p className="lede" style={{ margin: 0 }}>
                      Pause reason: {run.pause_reason}
                    </p>
                  ) : null}
                  <div className="runs-item-actions">
                    {run ? (
                      <button
                        type="button"
                        className={activeRunId === run.id ? "btn btn-primary" : "btn ghost-btn"}
                        onClick={() => setSelectedRunId(run.id)}
                      >
                        {activeRunId === run.id ? "Streaming this run" : "Watch event stream"}
                      </button>
                    ) : (
                      <span className="muted">Start Agent 4 to create a process run.</span>
                    )}
                    <Link to="/workspace" className="btn ghost-btn">
                      Open workspace
                    </Link>
                    {!isTerminal ? (
                      <button
                        type="button"
                        className="btn btn-complete"
                        disabled={isCompleting || completeMutation.isPending}
                        onClick={() => handleComplete(process)}
                      >
                        {isCompleting ? "Completing…" : "Mark as complete"}
                      </button>
                    ) : null}
                  </div>
                  <ProcessStatusCard process={process} />
                </article>
              );
            })}
          </div>

          <aside className="ops-panel runs-stream">
            <h2>Event stream</h2>
            <p className="lede">
              {activeRunId
                ? `Listening on process run ${activeRunId.slice(0, 8)}…`
                : "Select a run with an active process-run ID to stream events."}
            </p>
            <ul className="simple-list">
              {messages.length === 0 ? (
                <li>No events yet for the selected run.</li>
              ) : (
                messages.map((message, index) => (
                  <li key={`${message.event}-${index}`}>
                    <code className="mono-chip">{message.event}</code>
                    <span className="muted"> {message.data}</span>
                  </li>
                ))
              )}
            </ul>
          </aside>
        </div>
      )}
    </section>
  );
}
