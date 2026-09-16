import { useQuery } from "@tanstack/react-query";
import { ProcessStatusCard } from "../../components/process/ProcessStatusCard";
import { EmptyState } from "../../components/ui/EmptyState";
import { LoadingState } from "../../components/ui/LoadingState";
import { PageHeader } from "../../components/ui/PageHeader";
import { apiClient } from "../../lib/apiClient";
import { useProcessRunEvents } from "../../hooks/useProcessRunEvents";
import { useOrganization } from "../../providers/OrganizationProvider";

export function ActiveRunsPage() {
  const { activeOrganization } = useOrganization();
  const query = useQuery({
    queryKey: ["active-runs", activeOrganization?.id],
    queryFn: () => apiClient.listProcesses(),
    enabled: Boolean(activeOrganization?.id),
  });

  const active = (query.data ?? []).filter((p) =>
    ["executing", "paused", "blocked"].includes(p.status),
  );
  const runId = active[0]?.id ?? null;
  const { messages, status } = useProcessRunEvents(
    runId,
    runId ? apiClient.processRunEventsUrl(runId) : null,
  );

  if (query.isLoading) return <LoadingState label="Loading active runs…" />;

  return (
    <section>
      <PageHeader
        eyebrow="Execution"
        title="Active process runs"
        description="Live execution status with stream updates where available."
        actions={
          <span className="live-dot" aria-live="polite">
            Stream: {status}
          </span>
        }
      />
      {active.length === 0 ? (
        <EmptyState title="No active runs" description="Approved processes will appear here." />
      ) : (
        <div className="card-stack">
          {active.map((process) => (
            <ProcessStatusCard key={process.id} process={process} />
          ))}
        </div>
      )}
      <div className="ops-panel" style={{ marginTop: "1.25rem" }}>
        <h2>Event stream</h2>
        <ul className="simple-list">
          {messages.length === 0 ? (
            <li>No events yet for the selected run.</li>
          ) : (
            messages.map((message, index) => (
              <li key={`${message.event}-${index}`}>
                <code style={{ fontFamily: "var(--font-mono)", fontSize: "0.8rem" }}>
                  {message.event}
                </code>
                : {message.data}
              </li>
            ))
          )}
        </ul>
      </div>
    </section>
  );
}
