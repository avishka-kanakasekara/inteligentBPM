import type { ProcessRun, ProcessStatus, ProcessSummary } from "@bpm/frontend-types";

const TERMINAL_STATUSES = new Set(["completed", "cancelled", "failed", "rejected"]);

export const PROCESS_STATUSES = new Set<ProcessStatus>([
  "draft",
  "discovering",
  "plan_ready",
  "allocating",
  "allocated",
  "analyzing_risk",
  "risk_complete",
  "awaiting_approval",
  "approved",
  "rejected",
  "executing",
  "paused",
  "blocked",
  "failed",
  "completed",
  "cancelled",
]);

export type HistoryEntry = {
  key: string;
  title: string;
  status: string;
  when: string;
  process: ProcessSummary | null;
  run: ProcessRun | null;
  humanDecision: string | null;
  note: string | null;
};

function timestamp(value?: string | null) {
  const time = value ? new Date(value).getTime() : 0;
  return Number.isNaN(time) ? 0 : time;
}

export function isProcessStatus(status: string): status is ProcessStatus {
  return PROCESS_STATUSES.has(status as ProcessStatus);
}

export function selectHistoryEntries(
  processes: ProcessSummary[],
  runs: ProcessRun[],
): HistoryEntry[] {
  const byProcess = new Map(processes.map((process) => [process.id, process]));
  const covered = new Set<string>();
  const entries: HistoryEntry[] = [];

  for (const run of runs) {
    if (!TERMINAL_STATUSES.has(run.status)) continue;
    const process = byProcess.get(run.process_id) ?? null;
    if (process) covered.add(process.id);
    entries.push({
      key: run.id,
      title: process?.name ?? "Process no longer available",
      status: run.status,
      when: run.updated_at || run.created_at,
      process,
      run,
      humanDecision: process?.human_decision ?? null,
      note: run.pause_reason ?? null,
    });
  }

  for (const process of processes) {
    if (covered.has(process.id)) continue;
    const approval = process.approval_status;
    const terminalProcess = TERMINAL_STATUSES.has(process.status);
    const terminalApproval = approval === "rejected" || approval === "cancelled";
    if (!terminalProcess && !terminalApproval) continue;
    entries.push({
      key: process.id,
      title: process.name,
      status: terminalProcess ? process.status : (approval ?? process.status),
      when: process.updated_at,
      process,
      run: null,
      humanDecision: process.human_decision,
      note: null,
    });
  }

  return entries.sort((a, b) => timestamp(b.when) - timestamp(a.when));
}
