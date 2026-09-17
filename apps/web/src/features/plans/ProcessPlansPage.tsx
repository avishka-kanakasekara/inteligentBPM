import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import type { ProcessSummary } from "@bpm/frontend-types";
import {
  ApprovalBadge,
  ExecutionBadge,
  ProcessStatusBadge,
  RiskBadge,
} from "../../components/process/StatusBadges";
import { EmptyState } from "../../components/ui/EmptyState";
import { LoadingState } from "../../components/ui/LoadingState";
import { PageHeader } from "../../components/ui/PageHeader";
import { RetryState } from "../../components/ui/RetryState";
import { ApiError, apiClient } from "../../lib/apiClient";
import { useOrganization } from "../../providers/OrganizationProvider";

const COMPLETABLE = new Set([
  "approved",
  "executing",
  "paused",
  "blocked",
  "failed",
  "awaiting_approval",
  "risk_complete",
  "allocated",
  "plan_ready",
]);

function formatWhen(value: string) {
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

function PlanCard({
  process,
  onComplete,
  completing,
}: {
  process: ProcessSummary;
  onComplete: (process: ProcessSummary) => void;
  completing: boolean;
}) {
  const canComplete = COMPLETABLE.has(process.status);
  const isComplete = process.status === "completed";

  return (
    <article className="plan-card-row" aria-labelledby={`plan-${process.id}`}>
      <header className="plan-card-row-head">
        <div>
          <h2 id={`plan-${process.id}`}>{process.name}</h2>
          <p className="muted tight">Updated {formatWhen(process.updated_at)}</p>
        </div>
        <div className="badge-row">
          <ProcessStatusBadge status={process.status} />
          <RiskBadge level={process.risk_level} />
          <ApprovalBadge status={process.approval_status} />
          <ExecutionBadge status={process.execution_status} />
        </div>
      </header>

      <dl className="plan-meta-grid">
        <div>
          <dt>Missing information</dt>
          <dd>
            {process.missing_information.length
              ? process.missing_information.join("; ")
              : "None"}
          </dd>
        </div>
        <div>
          <dt>Unresolved assignments</dt>
          <dd>
            {process.unresolved_assignments.length
              ? process.unresolved_assignments.join("; ")
              : "None"}
          </dd>
        </div>
        <div>
          <dt>Policy evidence</dt>
          <dd>
            {process.policy_evidence.length ? process.policy_evidence.join("; ") : "None"}
          </dd>
        </div>
        <div>
          <dt>Human decision</dt>
          <dd>{process.human_decision ?? "Pending"}</dd>
        </div>
      </dl>

      {process.recommendations.length > 0 ? (
        <p className="plan-recommendation">
          <strong>Recommendation:</strong> {process.recommendations.join("; ")}
        </p>
      ) : null}

      <div className="plan-card-actions">
        <Link to="/discovery" className="btn ghost-btn">
          Open discovery
        </Link>
        <Link to="/runs" className="btn ghost-btn">
          Active runs
        </Link>
        {isComplete ? (
          <span className="status-pill tone-success">Project complete</span>
        ) : canComplete ? (
          <button
            type="button"
            className="btn btn-complete"
            disabled={completing}
            onClick={() => onComplete(process)}
          >
            {completing ? "Completing…" : "Mark as complete"}
          </button>
        ) : (
          <span className="muted">Complete becomes available after planning advances</span>
        )}
      </div>
    </article>
  );
}

export function ProcessPlansPage() {
  const { activeOrganization } = useOrganization();
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["process-plans", activeOrganization?.id],
    queryFn: () => apiClient.listProcesses(),
    enabled: Boolean(activeOrganization?.id),
  });

  const completeMutation = useMutation({
    mutationFn: (processId: string) => apiClient.completeProcess(processId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["process-plans"] }),
        queryClient.invalidateQueries({ queryKey: ["processes"] }),
        queryClient.invalidateQueries({ queryKey: ["active-runs"] }),
        queryClient.invalidateQueries({ queryKey: ["history"] }),
        queryClient.invalidateQueries({ queryKey: ["audit-events"] }),
      ]);
    },
  });

  if (query.isLoading) return <LoadingState label="Loading plans…" />;
  if (query.isError) {
    return <RetryState message={query.error.message} onRetry={() => void query.refetch()} />;
  }

  const items = query.data ?? [];
  const completingId =
    completeMutation.isPending && typeof completeMutation.variables === "string"
      ? completeMutation.variables
      : null;

  return (
    <section className="plans-page">
      <PageHeader
        eyebrow="Processes"
        title="Process plans"
        description="Versioned plans with missing data, assignments, and evidence."
        actions={
          <Link to="/discovery" className="btn btn-primary">
            Create process
          </Link>
        }
      />

      {completeMutation.isError ? (
        <p className="inline-notice is-error" role="alert">
          {completeMutation.error instanceof ApiError
            ? completeMutation.error.message
            : completeMutation.error.message}
        </p>
      ) : null}

      {items.length === 0 ? (
        <EmptyState title="No plans" description="Create a plan from discovery chat." />
      ) : (
        <div className="card-stack">
          {items.map((process) => (
            <PlanCard
              key={process.id}
              process={process}
              completing={completingId === process.id}
              onComplete={(item) => {
                if (
                  !window.confirm(
                    `Mark "${item.name}" as complete? This closes the process and any active runs.`,
                  )
                ) {
                  return;
                }
                completeMutation.mutate(item.id);
              }}
            />
          ))}
        </div>
      )}
    </section>
  );
}
