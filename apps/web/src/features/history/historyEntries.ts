import type { ProcessRun, ProcessSummary } from "@bpm/frontend-types";

const TERMINAL_STATUSES = new Set(["completed", "cancelled", "failed", "rejected"]);

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

export function selectHistoryEntries(
  processes: ProcessSummary[],
  runs: ProcessRun[],
): HistoryEntry[] {
  const byProcess = new Map(processes.map((process) => [process.id, process]));
  const entries: HistoryEntry[] = [];

  for (const run of runs) {
    if (!TERMINAL_STATUSES.has(run.status)) continue;
    const process = byProcess.get(run.process_id) ?? null;
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

  return entries.sort((a, b) => timestamp(b.when) - timestamp(a.when));
}
