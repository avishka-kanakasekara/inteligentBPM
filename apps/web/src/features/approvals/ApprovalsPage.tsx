import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApprovalBadge, RiskBadge } from "../../components/process/StatusBadges";
import { EmptyState } from "../../components/ui/EmptyState";
import { LoadingState } from "../../components/ui/LoadingState";
import { PageHeader } from "../../components/ui/PageHeader";
import { RetryState } from "../../components/ui/RetryState";
import { RequirePermission } from "../../components/RouteGuards";
import { ApiError, apiClient } from "../../lib/apiClient";
import { PERMISSIONS } from "../../lib/permissions";
import { useOrganization } from "../../providers/OrganizationProvider";
import type { ApprovalSummary } from "@bpm/frontend-types";

type DateFilterType = "all" | "today" | "yesterday" | "last_24h" | "last_7d" | "last_30d" | "custom";
type HourFilterType = "all" | "last_1h" | "last_4h" | "last_12h" | "morning" | "afternoon" | "evening" | "night" | "specific_hour";
type SortOrderType = "newest" | "oldest" | "risk_desc" | "risk_asc" | "name";

const RISK_WEIGHTS: Record<string, number> = {
  critical: 4,
  high: 3,
  medium: 2,
  low: 1,
};

function getApprovalDate(item: ApprovalSummary): Date | null {
  const raw = item.created_at || item.approval_history?.[0]?.at || item.updated_at;
  if (!raw) return null;
  const d = new Date(raw);
  return isNaN(d.getTime()) ? null : d;
}

function formatDisplayDate(dateStr?: string | null): string {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function getRelativeTime(dateStr?: string | null): string {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return "";
  const diffMs = Date.now() - d.getTime();
  if (diffMs < 0) return "just now";
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHours = Math.floor(diffMin / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

function toLocalDateString(d: Date): string {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function ApprovalsPage() {
  const { activeOrganization } = useOrganization();
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["approvals", activeOrganization?.id],
    queryFn: () => apiClient.listApprovals(),
    enabled: Boolean(activeOrganization?.id),
  });

  // Filter States
  const [searchQuery, setSearchQuery] = useState("");
  const [dateFilter, setDateFilter] = useState<DateFilterType>("all");
  const [customDate, setCustomDate] = useState("");
  const [hourFilter, setHourFilter] = useState<HourFilterType>("all");
  const [selectedHour, setSelectedHour] = useState<number>(9);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [riskLevelFilter, setRiskLevelFilter] = useState<string>("all");
  const [riskDecisionFilter, setRiskDecisionFilter] = useState<string>("all");
  const [sortOrder, setSortOrder] = useState<SortOrderType>("newest");

  const decideMutation = useMutation({
    mutationFn: async ({
      approvalId,
      decision,
    }: {
      approvalId: string;
      decision: "approved" | "rejected";
    }) => {
      const current = await apiClient.getApproval(approvalId);
      return apiClient.decideApproval(approvalId, {
        decision,
        note: decision === "approved" ? "Approved from approval center" : "Rejected from approval center",
        row_version: current.row_version,
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["approvals"] });
      void queryClient.invalidateQueries({ queryKey: ["processes"] });
    },
    onError: (err: unknown) => {
      const message =
        err instanceof ApiError
          ? `${err.message}${err.code ? ` (${err.code})` : ""}`
          : err instanceof Error
            ? err.message
            : "Decision failed";
      alert(message);
    },
  });

  const rawItems = query.data ?? [];
  const pendingCount = rawItems.filter((item) => item.status === "pending").length;

  // Filter & Sort Logic
  const filteredItems = useMemo(() => {
    const now = new Date();
    const todayStr = toLocalDateString(now);
    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    const yesterdayStr = toLocalDateString(yesterday);

    return rawItems
      .filter((item) => {
        // 1. Text Search Filter
        if (searchQuery.trim()) {
          const q = searchQuery.toLowerCase().trim();
          const matchName = (item.process_name || "").toLowerCase().includes(q);
          const matchId = item.id.toLowerCase().includes(q);
          const matchProcessId = (item.process_id || "").toLowerCase().includes(q);
          const matchRiskSummary = (item.risk_summary || "").toLowerCase().includes(q);
          const matchPolicy = (item.policy_evidence || []).some((p) => p.toLowerCase().includes(q));
          const matchRole = (item.required_roles || []).some((r) => r.toLowerCase().includes(q));
          const matchRiskDetail = (item.risk_items || []).some(
            (r) =>
              r.description.toLowerCase().includes(q) ||
              (r.policy_code && r.policy_code.toLowerCase().includes(q)),
          );
          if (
            !matchName &&
            !matchId &&
            !matchProcessId &&
            !matchRiskSummary &&
            !matchPolicy &&
            !matchRole &&
            !matchRiskDetail
          ) {
            return false;
          }
        }

        // 2. Status Filter
        if (statusFilter !== "all" && item.status !== statusFilter) {
          return false;
        }

        // 3. Risk Level Filter
        if (riskLevelFilter !== "all" && item.risk_level !== riskLevelFilter) {
          return false;
        }

        // 4. Risk Decision Filter
        if (riskDecisionFilter !== "all" && item.risk_decision !== riskDecisionFilter) {
          return false;
        }

        const itemDate = getApprovalDate(item);

        // 5. Date Filter
        if (dateFilter !== "all") {
          if (!itemDate) return false;
          const itemDateStr = toLocalDateString(itemDate);

          if (dateFilter === "today") {
            if (itemDateStr !== todayStr) return false;
          } else if (dateFilter === "yesterday") {
            if (itemDateStr !== yesterdayStr) return false;
          } else if (dateFilter === "last_24h") {
            const msDiff = now.getTime() - itemDate.getTime();
            if (msDiff < 0 || msDiff > 24 * 60 * 60 * 1000) return false;
          } else if (dateFilter === "last_7d") {
            const msDiff = now.getTime() - itemDate.getTime();
            if (msDiff < 0 || msDiff > 7 * 24 * 60 * 60 * 1000) return false;
          } else if (dateFilter === "last_30d") {
            const msDiff = now.getTime() - itemDate.getTime();
            if (msDiff < 0 || msDiff > 30 * 24 * 60 * 60 * 1000) return false;
          } else if (dateFilter === "custom" && customDate) {
            if (itemDateStr !== customDate) return false;
          }
        }

        // 6. Hour / Time Filter
        if (hourFilter !== "all") {
          if (!itemDate) return false;
          const itemHours = itemDate.getHours();

          if (hourFilter === "last_1h") {
            const msDiff = now.getTime() - itemDate.getTime();
            if (msDiff < 0 || msDiff > 60 * 60 * 1000) return false;
          } else if (hourFilter === "last_4h") {
            const msDiff = now.getTime() - itemDate.getTime();
            if (msDiff < 0 || msDiff > 4 * 60 * 60 * 1000) return false;
          } else if (hourFilter === "last_12h") {
            const msDiff = now.getTime() - itemDate.getTime();
            if (msDiff < 0 || msDiff > 12 * 60 * 60 * 1000) return false;
          } else if (hourFilter === "morning") {
            // 06:00 - 11:59
            if (itemHours < 6 || itemHours >= 12) return false;
          } else if (hourFilter === "afternoon") {
            // 12:00 - 17:59
            if (itemHours < 12 || itemHours >= 18) return false;
          } else if (hourFilter === "evening") {
            // 18:00 - 23:59
            if (itemHours < 18 || itemHours > 23) return false;
          } else if (hourFilter === "night") {
            // 00:00 - 05:59
            if (itemHours < 0 || itemHours >= 6) return false;
          } else if (hourFilter === "specific_hour") {
            if (itemHours !== Number(selectedHour)) return false;
          }
        }

        return true;
      })
      .sort((a, b) => {
        if (sortOrder === "newest") {
          const dateA = getApprovalDate(a)?.getTime() ?? 0;
          const dateB = getApprovalDate(b)?.getTime() ?? 0;
          return dateB - dateA;
        }
        if (sortOrder === "oldest") {
          const dateA = getApprovalDate(a)?.getTime() ?? 0;
          const dateB = getApprovalDate(b)?.getTime() ?? 0;
          return dateA - dateB;
        }
        if (sortOrder === "risk_desc") {
          const wA = RISK_WEIGHTS[a.risk_level] ?? 0;
          const wB = RISK_WEIGHTS[b.risk_level] ?? 0;
          return wB - wA;
        }
        if (sortOrder === "risk_asc") {
          const wA = RISK_WEIGHTS[a.risk_level] ?? 0;
          const wB = RISK_WEIGHTS[b.risk_level] ?? 0;
          return wA - wB;
        }
        if (sortOrder === "name") {
          return (a.process_name || "").localeCompare(b.process_name || "");
        }
        return 0;
      });
  }, [
    rawItems,
    searchQuery,
    statusFilter,
    riskLevelFilter,
    riskDecisionFilter,
    dateFilter,
    customDate,
    hourFilter,
    selectedHour,
    sortOrder,
  ]);

  const hasActiveFilters =
    Boolean(searchQuery.trim()) ||
    dateFilter !== "all" ||
    Boolean(customDate) ||
    hourFilter !== "all" ||
    statusFilter !== "all" ||
    riskLevelFilter !== "all" ||
    riskDecisionFilter !== "all";

  const resetFilters = () => {
    setSearchQuery("");
    setDateFilter("all");
    setCustomDate("");
    setHourFilter("all");
    setStatusFilter("all");
    setRiskLevelFilter("all");
    setRiskDecisionFilter("all");
    setSortOrder("newest");
  };

  return (
    <RequirePermission
      permission={PERMISSIONS.APPROVALS_READ}
      fallback={
        <EmptyState title="Access restricted" description="Approval center is not available." />
      }
    >
      <section>
        <PageHeader
          eyebrow="Governance"
          title="Risk and approval center"
          description="Deterministic risk decisions with policy evidence. Filter by date, hour, status, risk level, and policies."
          actions={
            <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
              <span className="status-pill tone-warning">{pendingCount} pending</span>
              <span className="status-pill tone-neutral">{rawItems.length} total</span>
            </div>
          }
        />

        {/* ── Filter Toolbar ────────────────────────────────────── */}
        <div className="approval-filter-bar panel" style={{ marginBottom: "1.25rem" }}>
          <div className="filter-controls-grid">
            {/* Search Input */}
            <div className="filter-control search-control">
              <label htmlFor="approval-search">Search approvals</label>
              <input
                id="approval-search"
                type="search"
                placeholder="Search process, policy, risk item..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>

            {/* Date Filter */}
            <div className="filter-control">
              <label htmlFor="approval-date-filter">Date</label>
              <select
                id="approval-date-filter"
                value={dateFilter}
                onChange={(e) => setDateFilter(e.target.value as DateFilterType)}
              >
                <option value="all">All Dates</option>
                <option value="today">Today</option>
                <option value="yesterday">Yesterday</option>
                <option value="last_24h">Past 24 Hours</option>
                <option value="last_7d">Past 7 Days</option>
                <option value="last_30d">Past 30 Days</option>
                <option value="custom">Specific Date…</option>
              </select>
            </div>

            {/* Custom Date Input (conditionally visible) */}
            {dateFilter === "custom" ? (
              <div className="filter-control">
                <label htmlFor="approval-custom-date">Select date</label>
                <input
                  id="approval-custom-date"
                  type="date"
                  value={customDate}
                  onChange={(e) => setCustomDate(e.target.value)}
                />
              </div>
            ) : null}

            {/* Hour Filter */}
            <div className="filter-control">
              <label htmlFor="approval-hour-filter">Hour / Time</label>
              <select
                id="approval-hour-filter"
                value={hourFilter}
                onChange={(e) => setHourFilter(e.target.value as HourFilterType)}
              >
                <option value="all">All Hours</option>
                <option value="last_1h">Past 1 Hour</option>
                <option value="last_4h">Past 4 Hours</option>
                <option value="last_12h">Past 12 Hours</option>
                <option value="morning">Morning (06:00 - 12:00)</option>
                <option value="afternoon">Afternoon (12:00 - 18:00)</option>
                <option value="evening">Evening (18:00 - 24:00)</option>
                <option value="night">Night (00:00 - 06:00)</option>
                <option value="specific_hour">Specific Hour…</option>
              </select>
            </div>

            {/* Specific Hour Selector (conditionally visible) */}
            {hourFilter === "specific_hour" ? (
              <div className="filter-control">
                <label htmlFor="approval-specific-hour">Select hour</label>
                <select
                  id="approval-specific-hour"
                  value={selectedHour}
                  onChange={(e) => setSelectedHour(Number(e.target.value))}
                >
                  {Array.from({ length: 24 }, (_, i) => (
                    <option key={i} value={i}>
                      {String(i).padStart(2, "0")}:00 - {String(i).padStart(2, "0")}:59
                    </option>
                  ))}
                </select>
              </div>
            ) : null}

            {/* Status Filter */}
            <div className="filter-control">
              <label htmlFor="approval-status-filter">Status</label>
              <select
                id="approval-status-filter"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
              >
                <option value="all">All Statuses</option>
                <option value="pending">Pending</option>
                <option value="approved">Approved</option>
                <option value="rejected">Rejected</option>
              </select>
            </div>

            {/* Risk Level Filter */}
            <div className="filter-control">
              <label htmlFor="approval-risk-filter">Risk Level</label>
              <select
                id="approval-risk-filter"
                value={riskLevelFilter}
                onChange={(e) => setRiskLevelFilter(e.target.value)}
              >
                <option value="all">All Risk Levels</option>
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </div>

            {/* Risk Decision Filter */}
            <div className="filter-control">
              <label htmlFor="approval-decision-filter">Decision</label>
              <select
                id="approval-decision-filter"
                value={riskDecisionFilter}
                onChange={(e) => setRiskDecisionFilter(e.target.value)}
              >
                <option value="all">All Decisions</option>
                <option value="CLEAR">CLEAR</option>
                <option value="APPROVAL_REQUIRED">APPROVAL_REQUIRED</option>
                <option value="BLOCKED">BLOCKED</option>
                <option value="INSUFFICIENT_INFORMATION">INSUFFICIENT_INFORMATION</option>
              </select>
            </div>

            {/* Sort Order */}
            <div className="filter-control">
              <label htmlFor="approval-sort-order">Sort by</label>
              <select
                id="approval-sort-order"
                value={sortOrder}
                onChange={(e) => setSortOrder(e.target.value as SortOrderType)}
              >
                <option value="newest">Newest First</option>
                <option value="oldest">Oldest First</option>
                <option value="risk_desc">Risk: High to Low</option>
                <option value="risk_asc">Risk: Low to High</option>
                <option value="name">Process Name (A-Z)</option>
              </select>
            </div>
          </div>

          {/* Active Filter Badges & Reset */}
          <div className="filter-summary-row">
            <span className="results-counter">
              Showing <strong>{filteredItems.length}</strong> of {rawItems.length} approvals
            </span>

            {hasActiveFilters ? (
              <div className="active-filter-pills">
                {searchQuery.trim() ? (
                  <button
                    type="button"
                    className="filter-pill-btn"
                    onClick={() => setSearchQuery("")}
                    title="Remove search query"
                  >
                    Query: "{searchQuery}" ✕
                  </button>
                ) : null}

                {dateFilter !== "all" ? (
                  <button
                    type="button"
                    className="filter-pill-btn"
                    onClick={() => {
                      setDateFilter("all");
                      setCustomDate("");
                    }}
                    title="Clear date filter"
                  >
                    Date: {dateFilter === "custom" && customDate ? customDate : dateFilter} ✕
                  </button>
                ) : null}

                {hourFilter !== "all" ? (
                  <button
                    type="button"
                    className="filter-pill-btn"
                    onClick={() => setHourFilter("all")}
                    title="Clear hour filter"
                  >
                    Hour: {hourFilter === "specific_hour" ? `${String(selectedHour).padStart(2, "0")}:00` : hourFilter} ✕
                  </button>
                ) : null}

                {statusFilter !== "all" ? (
                  <button
                    type="button"
                    className="filter-pill-btn"
                    onClick={() => setStatusFilter("all")}
                    title="Clear status filter"
                  >
                    Status: {statusFilter} ✕
                  </button>
                ) : null}

                {riskLevelFilter !== "all" ? (
                  <button
                    type="button"
                    className="filter-pill-btn"
                    onClick={() => setRiskLevelFilter("all")}
                    title="Clear risk level filter"
                  >
                    Risk: {riskLevelFilter} ✕
                  </button>
                ) : null}

                {riskDecisionFilter !== "all" ? (
                  <button
                    type="button"
                    className="filter-pill-btn"
                    onClick={() => setRiskDecisionFilter("all")}
                    title="Clear risk decision filter"
                  >
                    Decision: {riskDecisionFilter} ✕
                  </button>
                ) : null}

                <button
                  type="button"
                  className="ghost-btn reset-filters-btn"
                  onClick={resetFilters}
                >
                  Clear all filters
                </button>
              </div>
            ) : null}
          </div>
        </div>

        {query.isLoading ? <LoadingState label="Loading approvals…" /> : null}
        {query.isError ? (
          <RetryState message={query.error.message} onRetry={() => void query.refetch()} />
        ) : null}

        {/* Empty States */}
        {!query.isLoading && !query.isError && rawItems.length === 0 ? (
          <EmptyState title="No approvals" description="Nothing is waiting for a decision." />
        ) : null}

        {!query.isLoading && !query.isError && rawItems.length > 0 && filteredItems.length === 0 ? (
          <div className="panel empty-filter-state" style={{ textAlign: "center", padding: "2.5rem 1rem" }}>
            <h3 style={{ marginBottom: "0.5rem" }}>No approvals match the selected filters</h3>
            <p className="muted" style={{ marginBottom: "1.25rem" }}>
              Try loosening your date, hour, status, or search keywords to view more items.
            </p>
            <button type="button" className="btn-secondary" onClick={resetFilters}>
              Reset all filters
            </button>
          </div>
        ) : null}

        {/* Approval Items List */}
        <ul className="approval-list">
          {filteredItems.map((item) => {
            const rawTimestamp = item.created_at || item.approval_history?.[0]?.at || item.updated_at;
            const displayDate = formatDisplayDate(rawTimestamp);
            const relativeTime = getRelativeTime(rawTimestamp);

            return (
              <li key={item.id} className="approval-item risk-approval-card">
                <div className="badge-row">
                  <strong>{item.process_name || "Unknown process"}</strong>
                  <ApprovalBadge status={item.status} />
                  <RiskBadge level={item.risk_level} />
                  {item.risk_decision ? (
                    <span className="status-pill" data-decision={item.risk_decision}>
                      Decision: {item.risk_decision}
                    </span>
                  ) : null}
                  {displayDate ? (
                    <span className="timestamp-badge" title={displayDate}>
                      🕒 {displayDate} {relativeTime ? `(${relativeTime})` : ""}
                    </span>
                  ) : null}
                </div>

                <section className="risk-section" aria-labelledby={`risk-summary-${item.id}`}>
                  <h2 id={`risk-summary-${item.id}`}>Risk summary</h2>
                  <p>{item.risk_summary ?? "Risk analysis pending or unavailable."}</p>
                </section>

                <section className="risk-section" aria-labelledby={`policy-evidence-${item.id}`}>
                  <h2 id={`policy-evidence-${item.id}`}>Policy evidence</h2>
                  {(item.policy_evidence?.length ?? 0) === 0 ? (
                    <p>No policy evidence attached.</p>
                  ) : (
                    <ul className="check-list">
                      {item.policy_evidence.map((ev) => (
                        <li key={ev}>{ev}</li>
                      ))}
                    </ul>
                  )}
                  <p>
                    Sources:{" "}
                    {(item.source_refs ?? []).map((ref) => ref.label).join("; ") || "None"}
                  </p>
                </section>

                <section className="risk-section" aria-labelledby={`risk-detail-${item.id}`}>
                  <h2 id={`risk-detail-${item.id}`}>Risk detail</h2>
                  {(item.risk_items?.length ?? 0) === 0 ? (
                    <p>No detailed risk items.</p>
                  ) : (
                    <ul className="risk-item-list">
                      {item.risk_items?.map((risk) => (
                        <li key={risk.id}>
                          <strong>
                            {risk.category} · {risk.severity}
                            {risk.blocking ? " · blocking" : ""}
                          </strong>
                          <p>{risk.description}</p>
                          <p>Remediation: {risk.required_remediation}</p>
                          {risk.policy_code ? <p>Policy: {risk.policy_code}</p> : null}
                          {risk.required_approver ? (
                            <p>Approver: {risk.required_approver}</p>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                <section className="risk-section" aria-labelledby={`required-approvals-${item.id}`}>
                  <h2 id={`required-approvals-${item.id}`}>Required approvals</h2>
                  <p>Required roles: {(item.required_roles ?? []).join(", ") || "None"}</p>
                  <p>
                    Plan hash: {item.plan_snapshot_hash ?? "n/a"} · Risk hash:{" "}
                    {item.risk_snapshot_hash ?? item.snapshot_hash}
                  </p>
                  {item.process_id ? (
                    <p className="muted tight">Process ID: {item.process_id}</p>
                  ) : null}
                  {item.override_required ? (
                    <p className="blocked-callout">
                      Override workflow required — prohibited actions need audited authorization.
                    </p>
                  ) : null}
                </section>

                <section className="risk-section" aria-labelledby={`approval-history-${item.id}`}>
                  <h2 id={`approval-history-${item.id}`}>Approval history</h2>
                  {(item.approval_history?.length ?? 0) === 0 ? (
                    <p>Human decision: {item.decision_note ?? "Pending"}</p>
                  ) : (
                    <ul className="check-list">
                      {item.approval_history?.map((event, idx) => (
                        <li key={`${item.id}-hist-${idx}`}>
                          {event.action}
                          {event.actor ? ` · ${event.actor}` : ""}
                          {event.note ? ` — ${event.note}` : ""}
                          {event.at ? (
                            <span className="muted" style={{ marginLeft: "0.5rem", fontSize: "0.75rem" }}>
                              ({formatDisplayDate(event.at)})
                            </span>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                {item.risk_decision === "BLOCKED" || item.blocking_explanation ? (
                  <section
                    className="risk-section blocked-process"
                    aria-labelledby={`blocked-${item.id}`}
                  >
                    <h2 id={`blocked-${item.id}`}>Blocked process explanation</h2>
                    <p>
                      {item.blocking_explanation ??
                        "This process is blocked by deterministic policy rules and cannot proceed without an audited override."}
                    </p>
                  </section>
                ) : null}

                {item.status === "pending" ? (
                  <div className="plan-actions">
                    <button
                      type="button"
                      disabled={decideMutation.isPending}
                      onClick={() =>
                        void decideMutation.mutate({ approvalId: item.id, decision: "approved" })
                      }
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      className="btn-danger"
                      disabled={decideMutation.isPending}
                      onClick={() =>
                        void decideMutation.mutate({ approvalId: item.id, decision: "rejected" })
                      }
                    >
                      Reject
                    </button>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      </section>
    </RequirePermission>
  );
}

