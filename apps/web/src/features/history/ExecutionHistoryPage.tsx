import { useQuery } from "@tanstack/react-query";
import { ProcessStatusCard } from "../../components/process/ProcessStatusCard";
import { EmptyState } from "../../components/ui/EmptyState";
import { LoadingState } from "../../components/ui/LoadingState";
import { PageHeader } from "../../components/ui/PageHeader";
import { apiClient } from "../../lib/apiClient";
import { useOrganization } from "../../providers/OrganizationProvider";

export function ExecutionHistoryPage() {
  const { activeOrganization } = useOrganization();
  const query = useQuery({
    queryKey: ["history", activeOrganization?.id],
    queryFn: () => apiClient.listProcesses(),
    enabled: Boolean(activeOrganization?.id),
  });

  if (query.isLoading) return <LoadingState label="Loading history…" />;
  const history = (query.data ?? []).filter((p) =>
    ["completed", "cancelled", "failed", "rejected"].includes(p.status),
  );

  return (
    <section>
      <PageHeader
        eyebrow="Traceability"
        title="Execution history"
        description="Terminal and historical process outcomes with human decisions."
      />
      {history.length === 0 ? (
        <EmptyState
          title="No historical runs"
          description="Completed and cancelled runs will be listed here."
        />
      ) : (
        <div className="card-stack">
          {history.map((process) => (
            <ProcessStatusCard key={process.id} process={process} />
          ))}
        </div>
      )}
    </section>
  );
}
