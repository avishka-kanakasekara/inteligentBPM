import type { ApprovalStatus, ProcessStatus, RiskLevel } from "@bpm/frontend-types";

const PROCESS_LABELS: Record<ProcessStatus, string> = {
  draft: "Draft",
  discovering: "Discovering",
  plan_ready: "Plan ready",
  allocating: "Allocating",
  allocated: "Allocated",
  analyzing_risk: "Analyzing risk",
  risk_complete: "Risk complete",
  awaiting_approval: "Awaiting approval",
  approved: "Approved",
  rejected: "Rejected",
  executing: "Executing",
  paused: "Paused",
  blocked: "Blocked",
  failed: "Failed",
  completed: "Completed",
  cancelled: "Cancelled",
};

export function StatusPill({
  label,
  tone = "neutral",
}: {
  label: string;
  tone?: "neutral" | "info" | "success" | "warning" | "danger";
}) {
  return <span className={`status-pill tone-${tone}`}>{label}</span>;
}

export function ProcessStatusBadge({ status }: { status: ProcessStatus }) {
  const tone =
    status === "completed" || status === "approved"
      ? "success"
      : status === "blocked" || status === "failed" || status === "rejected"
        ? "danger"
        : status === "awaiting_approval" || status === "paused"
          ? "warning"
          : status === "executing"
            ? "info"
            : "neutral";
  return <StatusPill label={PROCESS_LABELS[status]} tone={tone} />;
}

export function RiskBadge({ level }: { level: RiskLevel | null }) {
  if (!level) return <StatusPill label="Risk n/a" />;
  const tone =
    level === "critical" || level === "high"
      ? "danger"
      : level === "medium"
        ? "warning"
        : "success";
  return <StatusPill label={`Risk: ${level}`} tone={tone} />;
}

export function ApprovalBadge({ status }: { status: ApprovalStatus | null }) {
  if (!status) return <StatusPill label="No approval" />;
  const tone =
    status === "approved"
      ? "success"
      : status === "rejected" || status === "invalidated"
        ? "danger"
        : status === "pending"
          ? "warning"
          : "neutral";
  return <StatusPill label={`Approval: ${status}`} tone={tone} />;
}

export function ExecutionBadge({ status }: { status: string | null }) {
  if (!status) return <StatusPill label="Not executing" />;
  return <StatusPill label={`Execution: ${status}`} tone="info" />;
}
