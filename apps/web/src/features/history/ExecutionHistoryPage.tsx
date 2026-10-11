import { useQuery } from "@tanstack/react-query";
import { EmptyState } from "../../components/ui/EmptyState";
import { LoadingState } from "../../components/ui/LoadingState";
import { PageHeader } from "../../components/ui/PageHeader";
import { RetryState } from "../../components/ui/RetryState";
import { apiClient } from "../../lib/apiClient";
import { useOrganization } from "../../providers/OrganizationProvider";
import { selectHistoryEntries } from "./historyEntries";

export function ExecutionHistoryPage() {
  const { activeOrganization } = useOrganization();
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
          {history.map((entry) => (
            <article key={entry.key} className="runs-item process-card">
              <h2>{entry.title}</h2>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
