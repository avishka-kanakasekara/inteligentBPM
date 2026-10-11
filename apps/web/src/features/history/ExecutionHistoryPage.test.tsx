import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ProcessRun, ProcessSummary } from "@bpm/frontend-types";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ExecutionHistoryPage } from "./ExecutionHistoryPage";
import { selectHistoryEntries } from "./historyEntries";

const listProcesses = vi.fn();
const listProcessRuns = vi.fn();

vi.mock("../../providers/OrganizationProvider", () => ({
  useOrganization: () => ({
    activeOrganization: {
      id: "11111111-1111-1111-1111-111111111111",
      name: "Demo",
    },
  }),
}));

vi.mock("../../lib/apiClient", () => ({
  apiClient: {
    listProcesses: (...args: unknown[]) => listProcesses(...args),
    listProcessRuns: (...args: unknown[]) => listProcessRuns(...args),
    getAllocation: vi.fn().mockResolvedValue(null),
    getRisk: vi.fn().mockResolvedValue(null),
    getExecution: vi.fn().mockResolvedValue(null),
  },
  ApiError: class ApiError extends Error {
    code?: string;
  },
}));

function process(overrides: Partial<ProcessSummary> = {}): ProcessSummary {
  return {
    id: "33333333-3333-3333-3333-333333333301",
    name: "Laptop procurement",
    status: "draft",
    risk_level: "medium",
    approval_status: "approved",
    execution_status: "completed",
    missing_information: [],
    unresolved_assignments: [],
    policy_evidence: [],
    source_refs: [],
    recommendations: [],
    human_decision: "Approved by manager",
    has_allocation: true,
    has_risk: true,
    has_execution: true,
    updated_at: "2026-10-10T12:00:00.000Z",
    ...overrides,
  };
}

function run(overrides: Partial<ProcessRun> = {}): ProcessRun {
  return {
    id: "55555555-5555-5555-5555-555555555503",
    organization_id: "11111111-1111-1111-1111-111111111111",
    process_id: "33333333-3333-3333-3333-333333333301",
    status: "completed",
    created_at: "2026-10-09T12:00:00.000Z",
    updated_at: "2026-10-11T12:00:00.000Z",
    dry_run: false,
    current_step_index: 4,
    pause_reason: null,
    ...overrides,
  };
}

describe("selectHistoryEntries", () => {
  it("includes finished runs even when the process itself is still draft", () => {
    const entries = selectHistoryEntries(
      [process(), process({ id: "33333333-3333-3333-3333-333333333302", name: "Still running" })],
      [
        run(),
        run({
          id: "55555555-5555-5555-5555-555555555501",
          process_id: "33333333-3333-3333-3333-333333333302",
          status: "executing",
          updated_at: "2026-10-12T12:00:00.000Z",
        }),
        run({
          id: "55555555-5555-5555-5555-555555555504",
          process_id: "33333333-3333-3333-3333-333333333301",
          status: "cancelled",
          updated_at: "2026-10-08T12:00:00.000Z",
          pause_reason: "Requester cancelled",
        }),
      ],
    );

    expect(entries.map((entry) => entry.status)).toEqual(["completed", "cancelled"]);
    expect(entries[0]?.title).toBe("Laptop procurement");
    expect(entries[0]?.humanDecision).toBe("Approved by manager");
    expect(entries[1]?.note).toBe("Requester cancelled");
  });

  it("keeps a rejected approval that never started a run", () => {
    const entries = selectHistoryEntries(
      [
        process({
          id: "33333333-3333-3333-3333-333333333309",
          name: "Rejected monitors",
          status: "draft",
          approval_status: "rejected",
          human_decision: "Rejected by compliance",
          has_execution: false,
          execution_status: null,
        }),
      ],
      [],
    );
    expect(entries).toHaveLength(1);
    expect(entries[0]?.status).toBe("rejected");
    expect(entries[0]?.humanDecision).toBe("Rejected by compliance");
  });
});

describe("ExecutionHistoryPage", () => {
  beforeEach(() => {
    listProcesses.mockReset();
    listProcessRuns.mockReset();
  });

  it("renders completed runs for processes that are still draft", async () => {
    listProcesses.mockResolvedValue([process()]);
    listProcessRuns.mockResolvedValue({
      items: [run()],
      meta: { total: 1, limit: 100, offset: 0 },
    });

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <ExecutionHistoryPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("heading", { name: "Laptop procurement" })).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("Approved by manager")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /run agent 2/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /show outcome/i }));
    expect(await screen.findByText(/agent 2 — resource allocation/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /run agent 2/i })).not.toBeInTheDocument();
  });
});
