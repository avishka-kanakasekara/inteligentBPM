import type { ApprovalSummary, ProcessRun, ProcessSummary } from "@bpm/frontend-types";

const FINISHED_RUN_STATUSES = new Set(["completed", "cancelled", "failed", "rejected"]);

export type DashboardMetrics = {
  activeRuns: number;
  pendingApprovals: number;
  completed: number;
  blocked: number;
  pendingProcessIds: string[];
  blockedProcessIds: string[];
};

function decision(process: ProcessSummary) {
  return (process.risk_decision || "").toUpperCase();
}

export function selectDashboardMetrics(
  processes: ProcessSummary[],
  runs: ProcessRun[],
  approvals: ApprovalSummary[],
): DashboardMetrics {
  const pending = new Set<string>();
  for (const approval of approvals) {
    if (approval.status !== "pending") continue;
    pending.add(approval.process_id ? `process:${approval.process_id}` : `approval:${approval.id}`);
  }
  for (const process of processes) {
    const awaiting =
      process.status === "awaiting_approval" ||
      process.approval_status === "pending" ||
      (decision(process) === "APPROVAL_REQUIRED" && !process.approval_status);
    if (awaiting) pending.add(`process:${process.id}`);
  }

  const blocked = new Set<string>();
  for (const process of processes) {
    if (
      process.status === "blocked" ||
      process.status === "failed" ||
      process.execution_status === "blocked" ||
      process.execution_status === "failed" ||
      decision(process) === "BLOCKED"
    ) {
      blocked.add(process.id);
    }
  }
  for (const run of runs) {
    if (run.status === "blocked" || run.status === "failed") blocked.add(run.process_id);
  }

  return {
    activeRuns: runs.filter((run) => !FINISHED_RUN_STATUSES.has(run.status)).length,
    pendingApprovals: pending.size,
    completed: runs.filter((run) => run.status === "completed").length,
    blocked: blocked.size,
    pendingProcessIds: [...pending]
      .filter((key) => key.startsWith("process:"))
      .map((key) => key.slice("process:".length)),
    blockedProcessIds: [...blocked],
  };
}
