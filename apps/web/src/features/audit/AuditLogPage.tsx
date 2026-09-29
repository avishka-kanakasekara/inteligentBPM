import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { AuditEvent } from "@bpm/frontend-types";
import { EmptyState } from "../../components/ui/EmptyState";
import { LoadingState } from "../../components/ui/LoadingState";
import { PageHeader } from "../../components/ui/PageHeader";
import { RetryState } from "../../components/ui/RetryState";
import { RequirePermission } from "../../components/RouteGuards";
import { apiClient } from "../../lib/apiClient";
import { PERMISSIONS } from "../../lib/permissions";
import { useOrganization } from "../../providers/OrganizationProvider";

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

function actorLabel(event: AuditEvent) {
  if (!event.actor_user_id) return "System";
  return `User ${event.actor_user_id.slice(0, 8)}`;
}

function detailLabel(event: AuditEvent) {
  const payload = event.payload ?? {};
  const candidates = [
    payload.process_name,
    payload.title,
    payload.reason,
    payload.decision,
    payload.message,
  ];
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) return value;
  }
  if (event.resource_id) return `${event.resource_type} · ${event.resource_id.slice(0, 8)}`;
  return event.resource_type;
}

function resultTone(result?: string | null) {
  const value = (result || "recorded").toLowerCase();
  if (["success", "approved", "completed", "ok"].includes(value)) return "tone-success";
  if (["blocked", "rejected", "failed", "error"].includes(value)) return "tone-danger";
  if (["pending", "paused", "warning"].includes(value)) return "tone-warning";
  return "tone-info";
}

export function AuditLogPage() {
  const { activeOrganization } = useOrganization();
  const [actionFilter, setActionFilter] = useState("");
  const [query, setQuery] = useState("");

  const eventsQuery = useQuery({
    queryKey: ["audit-events", activeOrganization?.id, actionFilter],
    queryFn: () =>
      apiClient.listAuditEvents({
        limit: 100,
        action: actionFilter.trim() || undefined,
      }),
    enabled: Boolean(activeOrganization?.id),
  });

  const events = useMemo(() => {
    const items = eventsQuery.data?.items ?? [];
    const needle = query.trim().toLowerCase();
    if (!needle) return items;
    return items.filter((event) => {
      const haystack = [
        event.action,
        event.resource_type,
        event.correlation_id ?? "",
        detailLabel(event),
        actorLabel(event),
        event.result ?? "",
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
    });
  }, [eventsQuery.data, query]);

  return (
    <RequirePermission
      permission={PERMISSIONS.AUDIT_READ}
      fallback={
        <EmptyState
          title="Access restricted"
          description="Audit log requires owner, admin, compliance, or auditor access."
        />
      }
    >
      <section className="audit-page">
        <PageHeader
          eyebrow="Compliance"
          title="Audit log"
          description="Append-only decisions and side effects for this organization."
          actions={
            <button
              type="button"
              className="ghost-btn"
              onClick={() => void eventsQuery.refetch()}
              disabled={eventsQuery.isFetching}
            >
              {eventsQuery.isFetching ? "Refreshing…" : "Refresh"}
            </button>
          }
        />

        <div className="toolbar audit-toolbar">
          <label>
            Filter action
            <input
              value={actionFilter}
              onChange={(e) => setActionFilter(e.target.value)}
              placeholder="e.g. approval, document, workflow"
            />
          </label>
          <label>
            Search
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Actor, detail, correlation…"
            />
          </label>
          <div className="audit-count">
            <span className="kpi-label">Showing</span>
            <strong>{events.length}</strong>
            <span className="muted">
              of {eventsQuery.data?.meta.total ?? events.length} events
            </span>
          </div>
        </div>

        {eventsQuery.isLoading ? (
          <LoadingState label="Loading audit events…" />
        ) : eventsQuery.isError ? (
          <RetryState
            title="Could not load audit log"
            message={(eventsQuery.error as Error).message}
            onRetry={() => void eventsQuery.refetch()}
          />
        ) : events.length === 0 ? (
          <EmptyState
            title="No audit events"
            description="Org actions, approvals, and execution side effects will appear here."
          />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Action</th>
                  <th scope="col">Actor</th>
                  <th scope="col">Detail</th>
                  <th scope="col">Result</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.id}>
                    <td className="muted">{formatWhen(event.created_at)}</td>
                    <td>
                      <code className="mono-chip">{event.action}</code>
                    </td>
                    <td>{actorLabel(event)}</td>
                    <td>
                      <div>{detailLabel(event)}</div>
                      {event.correlation_id ? (
                        <div className="muted tight">corr {event.correlation_id}</div>
                      ) : null}
                    </td>
                    <td>
                      <span className={`status-pill ${resultTone(event.result)}`}>
                        {event.result || "recorded"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </RequirePermission>
  );
}
