import type { ProcessSummary } from "@bpm/frontend-types";
import { ProcessStatusBadge, StatusPill } from "./StatusBadges";

type Tone = "neutral" | "info" | "success" | "warning" | "danger";

export function describeProcessActivity(
  process: ProcessSummary,
): { label: string; tone: Tone } | null {
  const risk = (process.risk_decision || "").toUpperCase();
  const execution = (process.execution_status || "").toLowerCase();
  const approval = process.approval_status;

  if (risk === "BLOCKED" || execution === "blocked" || process.status === "blocked") {
    return { label: "Blocked", tone: "danger" };
  }
  if (execution === "failed" || process.status === "failed") {
    return { label: "Failed", tone: "danger" };
  }
  if (approval === "rejected" || process.status === "rejected") {
    return { label: "Rejected", tone: "danger" };
  }
  if (approval === "pending" || process.status === "awaiting_approval") {
    return { label: "Awaiting approval", tone: "warning" };
  }
  if (execution === "completed" || process.status === "completed") {
    return { label: "Completed", tone: "success" };
  }
  if (execution === "cancelled" || process.status === "cancelled") {
    return { label: "Cancelled", tone: "neutral" };
  }
  if (execution === "executing" || process.status === "executing") {
    return { label: "Executing", tone: "info" };
  }
  if (execution === "paused" || process.status === "paused") {
    return { label: "Paused", tone: "warning" };
  }
  if (execution === "draft") {
    return { label: "Run started", tone: "info" };
  }
  if (approval === "approved") {
    return { label: "Approved", tone: "success" };
  }
  if (risk === "APPROVAL_REQUIRED") {
    return { label: "Approval required", tone: "warning" };
  }
  return null;
}

export function ProcessActivity({ process }: { process: ProcessSummary }) {
  const activity = describeProcessActivity(process);
  if (!activity) return <ProcessStatusBadge status={process.status} />;
  return <StatusPill label={activity.label} tone={activity.tone} />;
}
