import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ProcessStatusCard } from "../../components/process/ProcessStatusCard";
import { EmptyState } from "../../components/ui/EmptyState";
import { LoadingState } from "../../components/ui/LoadingState";
import { PageHeader } from "../../components/ui/PageHeader";
import { RetryState } from "../../components/ui/RetryState";
import { apiClient } from "../../lib/apiClient";
import { useOrganization } from "../../providers/OrganizationProvider";

export function ProcessPlansPage() {
  const { activeOrganization } = useOrganization();
  const query = useQuery({
    queryKey: ["process-plans", activeOrganization?.id],
    queryFn: () => apiClient.listProcesses(),
    enabled: Boolean(activeOrganization?.id),
  });

  if (query.isLoading) return <LoadingState label="Loading plans…" />;
  if (query.isError) {
    return <RetryState message={query.error.message} onRetry={() => void query.refetch()} />;
  }

  const items = query.data ?? [];
  return (
    <section>
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
      {items.length === 0 ? (
        <EmptyState title="No plans" description="Create a plan from discovery chat." />
      ) : (
        <div className="card-stack">
          {items.map((process) => (
            <ProcessStatusCard key={process.id} process={process} />
          ))}
        </div>
      )}
    </section>
  );
}
