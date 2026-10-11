import { useState, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ProcessSummary } from "@bpm/frontend-types";
import { ApiError, apiClient } from "../../lib/apiClient";

type HubTab = "overview" | "playbook" | "steer" | "commercial" | "playground" | "artifacts";

const NIL_RUN = "00000000-0000-0000-0000-000000000000";

interface Agent4ExecutionHubProps {
  process: ProcessSummary;
  onClose?: () => void;
  onRefreshParent?: () => void;
}

function realRunId(execution: any): string | undefined {
  const id = execution?.process_run_id;
  if (!id || id === NIL_RUN) return undefined;
  return String(id);
}

export function Agent4ExecutionHub({ process, onClose, onRefreshParent }: Agent4ExecutionHubProps) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<HubTab>("overview");
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ text: string; type: "info" | "success" | "error" } | null>(null);
  const [guidanceDraft, setGuidanceDraft] = useState("");
  const [skipReason, setSkipReason] = useState("");
  const [reportModalOpen, setReportModalOpen] = useState(false);
  const [reportData, setReportData] = useState<any | null>(null);
  const [comparisonResult, setComparisonResult] = useState<any | null>(null);
  const [selectedTool, setSelectedTool] = useState<string>("notification.send");
  const [playgroundArgs, setPlaygroundArgs] = useState<string>(
    JSON.stringify(
      { title: "Update", body: "Process update notice", idempotency_key: `notif-${Date.now()}` },
      null,
      2,
    ),
  );
  const [toolResult, setToolResult] = useState<any | null>(null);

  const {
    data: execution,
    refetch: refetchExecution,
    isError: executionError,
    error: executionErr,
  } = useQuery({
    queryKey: ["agent4-execution", process.id],
    queryFn: () => apiClient.getExecution(process.id),
    refetchInterval: busy ? 3000 : 10000,
    retry: 1,
  });

  const { data: toolsCatalog = [] } = useQuery({
    queryKey: ["tools-catalog"],
    queryFn: () => apiClient.listTools(),
    staleTime: 60000,
    retry: 1,
  });

  const { data: quotationsData, refetch: refetchQuotations } = useQuery({
    queryKey: ["process-quotations", process.id],
    queryFn: () => apiClient.listQuotations(process.id),
    retry: 1,
  });

  const { data: poData, refetch: refetchPOs } = useQuery({
    queryKey: ["process-pos", process.id],
    queryFn: () => apiClient.listPurchaseOrders(process.id),
    retry: 1,
  });

  const getToolTemplate = useCallback((toolName: string) => {
    const ts = Date.now();
    switch (toolName) {
      case "company.employee_lookup":
        return JSON.stringify({ query: "Operations" }, null, 2);
      case "company.manager_lookup":
        return JSON.stringify({ employee_id: "emp-001" }, null, 2);
      case "supplier.search":
        return JSON.stringify({ query: "Hardware", approved_only: true }, null, 2);
      case "supplier.request_quote":
        return JSON.stringify(
          {
            supplier_id: "sup-001",
            product_sku: "LAPTOP-X",
            quantity: 5,
            subject: "RFQ: 5x Laptop X",
            body: "Please provide your formal quote.",
            idempotency_key: `rfq-${ts}`,
          },
          null,
          2,
        );
      case "email.create_draft":
      case "email.send":
        return JSON.stringify(
          {
            to_employee_id: "casey@acme.test",
            subject: "Process Authorization Notice",
            body: "Your procurement order has been reviewed.",
            idempotency_key: `email-${ts}`,
          },
          null,
          2,
        );
      case "notification.send":
        return JSON.stringify(
          {
            title: "Execution Update",
            body: "Process step reached checkpoint.",
            idempotency_key: `notif-${ts}`,
          },
          null,
          2,
        );
      case "calendar.create_event":
        return JSON.stringify(
          {
            title: "Procurement Review Meeting",
            start_at: new Date(Date.now() + 86400000).toISOString(),
            attendees: ["casey@acme.test"],
            description: "Review supplier terms",
            idempotency_key: `cal-${ts}`,
          },
          null,
          2,
        );
      case "task.assign":
        return JSON.stringify(
          {
            title: "Inspect Received Equipment",
            assignee_id: "emp-001",
            description: "Verify delivery matches PO",
            idempotency_key: `task-${ts}`,
          },
          null,
          2,
        );
      case "document.generate":
        return JSON.stringify(
          {
            title: "Procurement Summary Memo",
            doc_type: "memo",
            content: "Comprehensive overview of laptop acquisition and vendor selection.",
            idempotency_key: `doc-${ts}`,
          },
          null,
          2,
        );
      case "quotation.compare":
        return JSON.stringify({ quotation_ids: ["quote-001", "quote-002"], explain: true }, null, 2);
      default:
        return JSON.stringify({ idempotency_key: `tool-${ts}` }, null, 2);
    }
  }, []);

  useEffect(() => {
    setPlaygroundArgs(getToolTemplate(selectedTool));
  }, [selectedTool, getToolTemplate]);

  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  useEffect(() => {
    if (executionError && executionErr) {
      const msg =
        executionErr instanceof ApiError
          ? executionErr.message
          : (executionErr as Error)?.message || "Failed to load execution";
      setNotice({ text: msg, type: "error" });
    }
  }, [executionError, executionErr]);

  const runAction = async (label: string, fn: () => Promise<any>, successMsg: string) => {
    setBusy(label);
    setNotice({ text: `Processing ${label}…`, type: "info" });
    try {
      await fn();
      setNotice({ text: successMsg, type: "success" });
      await Promise.all([
        refetchExecution(),
        refetchQuotations(),
        refetchPOs(),
        queryClient.invalidateQueries({ queryKey: ["processes"] }),
        queryClient.invalidateQueries({ queryKey: ["active-runs"] }),
        queryClient.invalidateQueries({ queryKey: ["history"] }),
      ]);
      onRefreshParent?.();
    } catch (err: any) {
      const msg =
        err instanceof ApiError ? `${err.message} (${err.code || "ERROR"})` : err?.message || "Action failed";
      setNotice({ text: msg, type: "error" });
    } finally {
      setBusy(null);
    }
  };

  const handleStartOrAdvance = () => {
    void runAction(
      "auto-run",
      async () => {
        let state: any = execution;
        const needsStart =
          !state ||
          state.status === "not_run" ||
          state.status === "draft" ||
          !realRunId(state);

        if (needsStart) {
          state = await apiClient.startExecution(process.id, {
            dry_run: false,
            auto_run: true,
            max_steps: 80,
          });
        }

        let guard = 0;
        while (
          guard < 6 &&
          state &&
          ["executing", "approved", "draft"].includes(String(state.status || ""))
        ) {
          state = await apiClient.advanceExecution(process.id, 80);
          guard += 1;
          const idx = Number(state?.current_step_index ?? 0);
          const total = Number(state?.execution_intelligence?.plan_step_count ?? 0);
          if (total > 0 && idx >= total) break;
          if (
            ["completed", "cancelled", "failed", "paused", "awaiting_approval", "blocked"].includes(
              String(state.status || ""),
            )
          ) {
            break;
          }
        }
        return state;
      },
      "Agent 4 finished the process.",
    );
  };

  const handlePause = () => {
    void runAction("pause", () => apiClient.pauseExecution(process.id), "Execution paused.");
  };

  const handleResume = () => {
    void runAction("resume", async () => {
      await apiClient.resumeExecution(process.id);
      return apiClient.advanceExecution(process.id, 80);
    }, "Agent 4 resumed and kept working.");
  };

  const handleCancel = () => {
    if (!window.confirm("Cancel this execution run? This will abort all pending steps.")) return;
    void runAction("cancel", () => apiClient.cancelExecution(process.id), "Execution cancelled.");
  };

  const handleReset = () => {
    if (!window.confirm("Reset execution run back to initial step?")) return;
    void runAction("reset", () => apiClient.resetExecution(process.id), "Execution reset to start.");
  };

  const handlePlaygroundInvoke = () => {
    let parsed: Record<string, unknown> = {};
    try {
      parsed = JSON.parse(playgroundArgs);
    } catch {
      setNotice({ text: "Invalid JSON in arguments.", type: "error" });
      return;
    }
    void runAction(
      "playground",
      async () => {
        const res = await apiClient.invokeTool(
          process.id,
          selectedTool,
          parsed,
          realRunId(execution),
        );
        setToolResult(res);
        return res;
      },
      `Tool ${selectedTool} executed successfully.`,
    );
  };

  const handleCompareQuotations = () => {
    const quotes = quotationsData?.items || [];
    if (quotes.length < 1) {
      setNotice({ text: "No quotations available to compare.", type: "info" });
      return;
    }
    const ids = quotes.map((q: any) => q.quotation_id || q.id);
    void runAction(
      "compare-quotes",
      async () => {
        const res = await apiClient.compareQuotations(process.id, ids, true);
        setComparisonResult(res);
        return res;
      },
      "Quotations analyzed with AI scoring.",
    );
  };

  const handleOpenReport = async () => {
    try {
      const rep = await apiClient.getExecutionReport(process.id, realRunId(execution));
      setReportData(rep);
      setReportModalOpen(true);
    } catch (e: any) {
      setNotice({ text: "Could not load report: " + (e?.message || ""), type: "error" });
    }
  };

  const runStatus = execution?.status || "not_run";
  const isExecuting = runStatus === "executing";
  const isPaused = runStatus === "paused";
  const isAwaiting = runStatus === "awaiting_approval";
  const isTerminal = runStatus === "completed" || runStatus === "cancelled";
  const invocations: any[] = execution?.tool_invocations || [];
  const currentStep = execution?.current_step_index ?? 0;
  const intelligence = execution?.execution_intelligence || null;
  const checklist = intelligence?.step_checklist || null;
  const outbound = intelligence?.outbound_already_sent || [];
  const emailSendCount = intelligence?.email_send_count ?? 0;
  const planStepCount = intelligence?.plan_step_count ?? 0;
  const remainingTools: string[] = checklist?.remaining || [];
  const executedTools: string[] = intelligence?.executed_tools || [];
  const playbook: any[] = execution?.playbook || [];
  const scorecard = execution?.scorecard || null;
  const operator = execution?.operator || null;
  const activity: any[] = execution?.agent_activity || [];
  const hasScore = Boolean(scorecard && (scorecard.tools_total > 0 || scorecard.steps_total > 0));
  const toolBreakdown = invocations.reduce((acc: Record<string, number>, inv: any) => {
    const name = String(inv.tool_name || "unknown");
    acc[name] = (acc[name] || 0) + 1;
    return acc;
  }, {});
  const runId = realRunId(execution);
  const progressPct = planStepCount
    ? Math.min(100, Math.round((currentStep / planStepCount) * 100))
    : 0;

  const handleSteer = async () => {
    await runAction(
      "steer",
      () =>
        apiClient.steerExecution(process.id, {
          guidance: guidanceDraft,
          run_id: runId,
        }),
      "Operator guidance saved — Agent 4 will follow it on the next advance.",
    );
  };

  const handleToggleEmailGuard = async (enabled: boolean) => {
    await runAction(
      "steer",
      () =>
        apiClient.steerExecution(process.id, {
          email_guard_enabled: enabled,
          unblock_tools: enabled ? ["email.send"] : undefined,
          run_id: runId,
        }),
      enabled ? "Email guard on — repeats blocked." : "Email guard relaxed.",
    );
  };

  const handleBlockEmail = async () => {
    await runAction(
      "steer",
      () =>
        apiClient.steerExecution(process.id, {
          block_tools: ["email.send"],
          run_id: runId,
        }),
      "email.send blocked for this run.",
    );
  };

  const handleSkipTool = async (toolName: string, advanceStep = false) => {
    await runAction(
      "skip",
      () =>
        apiClient.skipExecutionProposal(process.id, {
          tool_name: toolName,
          reason: skipReason || "Operator skipped tool",
          advance_step: advanceStep,
          run_id: runId,
        }),
      advanceStep ? "Tool skipped and step advanced." : "Tool skipped.",
    );
    setSkipReason("");
  };

  const tabs: { id: HubTab; label: string }[] = [
    { id: "overview", label: `Overview${invocations.length ? ` · ${invocations.length}` : ""}` },
    { id: "playbook", label: `Playbook${playbook.length ? ` · ${playbook.length}` : ""}` },
    {
      id: "steer",
      label: `Steer${(operator?.stuck_strikes || 0) > 0 ? ` · ${operator.stuck_strikes}` : ""}`,
    },
    { id: "commercial", label: `Quotes · ${quotationsData?.items?.length || 0}` },
    { id: "playground", label: "Tools" },
    { id: "artifacts", label: "Artifacts" },
  ];

  return createPortal(
    <div className="agent4-hub-modal-overlay" role="dialog" aria-labelledby="agent4-hub-title" aria-modal="true">
      <div className="agent4-hub-container">
        <header className="agent4-hub-header">
          <div className="agent4-hub-header-bg" aria-hidden="true" />
          <div className="agent4-hub-header-left">
            <div className="agent4-badge-cluster">
              <span className="agent-number-badge">Agent 4</span>
              <span
                className={`status-pill ${
                  isExecuting
                    ? "tone-info"
                    : isPaused || isAwaiting
                      ? "tone-warning"
                      : runStatus === "completed"
                        ? "tone-success"
                        : runStatus === "cancelled"
                          ? "tone-danger"
                          : "tone-neutral"
                }`}
              >
                {runStatus.replace(/_/g, " ")}
              </span>
            </div>
            <h2 id="agent4-hub-title">{process.name}</h2>
            <p className="agent4-hub-lede">
              Reads the plan, decides the next action, and finishes the process — quotes, orders, documents, and notifications.
            </p>
            {planStepCount > 0 && (
              <div className="agent4-hero-progress">
                <div className="agent4-hero-progress-meta">
                  <span>
                    Step {Math.min(currentStep + 1, planStepCount)} of {planStepCount}
                  </span>
                  <span>{progressPct}%</span>
                </div>
                <div className="agent4-progress-track">
                  <div className="agent4-progress-fill" style={{ width: `${progressPct}%` }} />
                </div>
              </div>
            )}
          </div>

          <div className="agent4-hub-header-right">
            <button type="button" className="btn btn-sm btn-ghost agent4-header-btn" onClick={() => void handleOpenReport()}>
              Audit report
            </button>
            {onClose && (
              <button
                type="button"
                className="btn btn-sm btn-ghost close-btn"
                onClick={onClose}
                aria-label="Close modal"
              >
                ✕
              </button>
            )}
          </div>
        </header>

        {notice && (
          <div className={`agent4-notice ${notice.type}`} role="status">
            <span>{notice.text}</span>
            <button type="button" className="dismiss-btn" onClick={() => setNotice(null)}>
              ✕
            </button>
          </div>
        )}

        <div className="agent4-control-bar">
          <p className="agent4-agent-status">
            {busy === "auto-run"
              ? "Working through the plan…"
              : isExecuting
                ? "In progress"
                : runStatus === "completed"
                  ? "Process complete"
                  : "Ready to run the full process"}
          </p>

          <div className="action-buttons-group">
            {!isTerminal && (
              <>
                <button
                  type="button"
                  className="btn btn-primary agent4-primary-cta"
                  disabled={busy !== null || isExecuting}
                  onClick={handleStartOrAdvance}
                >
                  {busy === "auto-run" ? "Running the process…" : "Run process"}
                </button>

                {isExecuting && (
                  <button type="button" className="btn btn-warning" onClick={handlePause} disabled={busy !== null}>
                    Pause
                  </button>
                )}

                {(isPaused || isAwaiting) && (
                  <button type="button" className="btn btn-success" onClick={handleResume} disabled={busy !== null}>
                    Resume
                  </button>
                )}

                <button type="button" className="btn btn-ghost" onClick={handleCancel} disabled={busy !== null}>
                  Cancel
                </button>
              </>
            )}

            {isTerminal && (
              <button type="button" className="btn btn-ghost" onClick={handleReset} disabled={busy !== null}>
                Reset run
              </button>
            )}
          </div>
        </div>

        {(operator?.guidance ||
          (operator?.blocked_tools || []).length > 0 ||
          (operator?.stuck_strikes || 0) > 0 ||
          hasScore) && (
          <div className="agent4-operator-strip">
            {hasScore && (
              <span className="agent4-strip-chip">
                Score {scorecard.success_rate}% · {scorecard.tools_successful ?? 0} tools
              </span>
            )}
            {operator?.guidance ? (
              <span className="agent4-strip-chip tone-info" title={operator.guidance}>
                Guided: {String(operator.guidance).slice(0, 72)}
                {String(operator.guidance).length > 72 ? "…" : ""}
              </span>
            ) : null}
            {(operator?.blocked_tools || []).length > 0 && (
              <span className="agent4-strip-chip tone-warning">
                Blocked {(operator.blocked_tools as string[]).join(", ")}
              </span>
            )}
            {(operator?.stuck_strikes || 0) > 0 && (
              <span className="agent4-strip-chip tone-danger">
                Stuck ×{operator.stuck_strikes} — open Steer
              </span>
            )}
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => setActiveTab("steer")}>
              Steer
            </button>
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => setActiveTab("playbook")}>
              Playbook
            </button>
          </div>
        )}

        <nav className="agent4-nav-tabs" role="tablist">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.id}
              className={activeTab === tab.id ? "is-active" : ""}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        <main className="agent4-tab-content">
          {activeTab === "overview" && (
            <div className="overview-tab">
              <section className="agent4-activity">
                <div className="stepper-header">
                  <div>
                    <span className="eyebrow">Agent</span>
                    <h3>What Agent 4 is doing</h3>
                  </div>
                </div>
                {activity.length === 0 ? (
                  <p className="muted">
                    Hit Run process. Agent 4 reads the plan, picks each tool, recovers from failures, and stops only when the process is done or a human decision is required.
                  </p>
                ) : (
                  <ol className="agent4-activity-list">
                    {activity.slice(-18).map((item: any, idx: number) => (
                      <li key={`${item.at}-${idx}`} className={`agent4-activity-item kind-${item.kind || "note"}`}>
                        <span className="agent4-activity-kind">{item.kind || "note"}</span>
                        <p>{item.message}</p>
                      </li>
                    ))}
                  </ol>
                )}
              </section>
              <div className="agent4-intel-grid">
                <div className="agent4-intel-card">
                  <span className="eyebrow">Plan progress</span>
                  <h3>
                    Step {Math.min(currentStep + 1, Math.max(planStepCount, 1))}
                    {planStepCount ? ` of ${planStepCount}` : ""}
                  </h3>
                  <p className="muted tight">{intelligence?.current_step_title || "Ready when you are"}</p>
                </div>
                <div className="agent4-intel-card">
                  <span className="eyebrow">Step checklist</span>
                  <h3>{checklist?.complete ? "Step complete" : "In progress"}</h3>
                  <p className="muted tight">Kind: {checklist?.step_kind || "general"}</p>
                  {remainingTools.length > 0 ? (
                    <ul className="agent4-checklist">
                      {remainingTools.map((tool) => (
                        <li key={tool}>
                          <code>{tool}</code> still needed
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="muted tight">No unfinished outcomes for this step.</p>
                  )}
                </div>
                <div className="agent4-intel-card">
                  <span className="eyebrow">Outbound mail guard</span>
                  <h3>
                    {emailSendCount}/{intelligence?.max_email_send_per_run ?? 2} emails sent
                  </h3>
                  <p className="muted tight">Same recipient will not be emailed again in this run.</p>
                  {outbound.length > 0 ? (
                    <ul className="agent4-checklist">
                      {outbound.slice(0, 4).map((item: any, idx: number) => (
                        <li key={`${item.tool}-${idx}`}>
                          <code>{item.tool}</code>
                          {item.recipient ? ` → ${item.recipient}` : ""}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="muted tight">No outbound messages yet.</p>
                  )}
                </div>
                <div className="agent4-intel-card">
                  <span className="eyebrow">Tools used</span>
                  <h3>{executedTools.length} unique</h3>
                  <div className="agent4-tool-chips">
                    {Object.keys(toolBreakdown).length === 0 ? (
                      <span className="muted">None yet</span>
                    ) : (
                      Object.entries(toolBreakdown).map(([name, count]) => (
                        <span key={name} className="agent4-tool-chip">
                          {name} ×{count as number}
                        </span>
                      ))
                    )}
                  </div>
                </div>
                {hasScore && (
                  <div className="agent4-intel-card agent4-scorecard">
                    <span className="eyebrow">Run scorecard</span>
                    <h3>{scorecard.success_rate}% success</h3>
                    <ul className="agent4-scorecard-stats">
                      <li>
                        {scorecard.tools_successful ?? 0} ok · {scorecard.tools_failed_or_denied ?? 0} failed
                      </li>
                      <li>
                        {scorecard.steps_completed ?? 0}/{scorecard.steps_total ?? 0} steps
                      </li>
                      <li>
                        Quotes {scorecard.quotes_requested ?? 0} · POs{" "}
                        {scorecard.purchase_orders_submitted ?? 0} · Docs {scorecard.documents ?? 0}
                      </li>
                    </ul>
                  </div>
                )}
              </div>

              <div className="stepper-card">
                <div className="stepper-header">
                  <div>
                    <span className="eyebrow">Execution timeline</span>
                    <h3>What Agent 4 actually ran</h3>
                  </div>
                  {execution?.pause_reason && runStatus !== "not_run" && (
                    <div className="pause-callout">
                      <strong>Pause:</strong> {execution.pause_reason}
                    </div>
                  )}
                </div>

                <div className="tool-timeline">
                  {invocations.length === 0 ? (
                    <div className="agent4-empty-state">
                      <p>Run the process. Agent 4 will work through every plan step on its own.</p>
                      <button
                        type="button"
                        className="btn btn-primary"
                        disabled={busy !== null}
                        onClick={handleStartOrAdvance}
                      >
                        Begin execution
                      </button>
                    </div>
                  ) : (
                    <ul className="timeline-list">
                      {invocations.map((inv: any, idx: number) => {
                        const isOk = inv.status === "executed" || inv.status === "replayed";
                        return (
                          <li key={inv.id || idx} className="timeline-item">
                            <span className={`timeline-marker ${isOk ? "ok" : "failed"}`}>
                              {isOk ? "✓" : "✕"}
                            </span>
                            <div className="timeline-details">
                              <div className="timeline-row">
                                <strong className="tool-code">{inv.tool_name}</strong>
                                <span className={`status-tag ${inv.status}`}>{inv.status}</span>
                                <time className="timestamp">
                                  {inv.created_at ? new Date(inv.created_at).toLocaleTimeString() : "—"}
                                </time>
                              </div>
                              {inv.error && (
                                <p className="timeline-error">
                                  Error ({inv.error.code}): {inv.error.message}
                                </p>
                              )}
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              </div>
            </div>
          )}

          {activeTab === "playbook" && (
            <div className="playbook-tab">
              <div className="proposal-card agent4-panel">
                <div className="proposal-header">
                  <span className="eyebrow">Live playbook</span>
                  <h3>Plan steps with live status</h3>
                </div>
                {playbook.length === 0 ? (
                  <div className="agent4-empty-state">
                    <p>No plan steps on this run yet. Start execution to hydrate the playbook.</p>
                  </div>
                ) : (
                  <ol className="agent4-playbook-list">
                    {playbook.map((step: any) => (
                      <li
                        key={step.index}
                        className={`agent4-playbook-step status-${step.status || "pending"}`}
                      >
                        <div className="agent4-playbook-step-head">
                          <span
                            className={`status-pill tone-${
                              step.status === "done" || step.status === "complete"
                                ? "success"
                                : step.status === "active"
                                  ? "info"
                                  : "neutral"
                            }`}
                          >
                            {String(step.status || "pending")}
                          </span>
                          <strong>
                            {step.index + 1}. {step.title}
                          </strong>
                          {step.step_kind ? <code>{step.step_kind}</code> : null}
                        </div>
                        {step.description ? <p className="muted tight">{step.description}</p> : null}
                        {(step.remaining || []).length > 0 && (
                          <p className="tight">
                            Still needed:{" "}
                            {(step.remaining as string[]).map((t) => (
                              <code key={t} className="agent4-tool-chip">
                                {t}
                              </code>
                            ))}
                          </p>
                        )}
                        {(step.allowed_tools || []).length > 0 && (
                          <div className="agent4-tool-chips">
                            {(step.allowed_tools as string[]).slice(0, 8).map((t) => (
                              <span key={t} className="agent4-tool-chip">
                                {t}
                              </span>
                            ))}
                          </div>
                        )}
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            </div>
          )}

          {activeTab === "steer" && (
            <div className="steer-tab">
              <div className="proposal-card agent4-panel">
                <div className="proposal-header">
                  <span className="eyebrow">Operator steer</span>
                  <h3>Guide the next steps</h3>
                </div>
                <p className="muted">
                  Tell Agent 4 what to prioritize. Guidance and blocks persist on the run.
                </p>
                {(operator?.stuck_strikes || 0) > 0 && (
                  <div className="pause-callout">
                    Stuck watchdog: {operator.stuck_strikes} repeated proposals. Skip the looping tool or add
                    guidance.
                  </div>
                )}
                <textarea
                  className="input agent4-steer-textarea"
                  rows={4}
                  placeholder="e.g. Request dual RFQs then compare quotes — do not email again"
                  value={guidanceDraft}
                  onChange={(e) => setGuidanceDraft(e.target.value)}
                  onFocus={() => {
                    if (!guidanceDraft && operator?.guidance) {
                      setGuidanceDraft(String(operator.guidance));
                    }
                  }}
                />
                {operator?.guidance && !guidanceDraft ? (
                  <p className="muted tight">Current: {operator.guidance}</p>
                ) : null}
                <div className="proposal-actions">
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => void handleSteer()}
                    disabled={busy !== null || !(guidanceDraft || "").trim() || !runId}
                  >
                    Save guidance
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => void handleBlockEmail()}
                    disabled={busy !== null || !runId}
                  >
                    Block email.send
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => void handleToggleEmailGuard(operator?.email_guard_enabled === false)}
                    disabled={busy !== null || !runId}
                  >
                    {operator?.email_guard_enabled === false ? "Enable email guard" : "Relax email guard"}
                  </button>
                </div>

                {remainingTools.length > 0 && (
                  <div className="agent4-skip-panel">
                    <span className="meta-label">Skip a remaining tool</span>
                    <input
                      type="text"
                      className="input"
                      placeholder="Optional reason"
                      value={skipReason}
                      onChange={(e) => setSkipReason(e.target.value)}
                    />
                    <div className="proposal-actions">
                      {remainingTools.slice(0, 4).map((tool) => (
                        <button
                          key={tool}
                          type="button"
                          className="btn btn-sm btn-ghost"
                          disabled={busy !== null || !runId}
                          onClick={() => void handleSkipTool(tool, false)}
                        >
                          Skip {tool}
                        </button>
                      ))}
                      <button
                        type="button"
                        className="btn btn-sm btn-ghost"
                        disabled={busy !== null || !runId}
                        onClick={() => void handleSkipTool(remainingTools[0], true)}
                      >
                        Skip &amp; advance step
                      </button>
                    </div>
                  </div>
                )}

                {(operator?.blocked_tools || []).length > 0 && (
                  <div className="agent4-tool-chips" style={{ marginTop: "1rem" }}>
                    <span className="meta-label">Blocked:</span>
                    {(operator.blocked_tools as string[]).map((t) => (
                      <span key={t} className="agent4-tool-chip">
                        {t}
                      </span>
                    ))}
                  </div>
                )}
                {(operator?.skipped_proposals || []).length > 0 && (
                  <div style={{ marginTop: "1rem" }}>
                    <span className="meta-label">Recent skips</span>
                    <ul className="agent4-checklist">
                      {(operator.skipped_proposals as any[])
                        .slice(-5)
                        .reverse()
                        .map((s, i) => (
                          <li key={`${s.tool_name}-${i}`}>
                            <code>{s.tool_name}</code>
                            {s.reason ? ` — ${s.reason}` : ""}
                          </li>
                        ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === "commercial" && (
            <div className="commercial-tab">
              <div className="commercial-actions-bar">
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={handleCompareQuotations}
                  disabled={busy !== null || (quotationsData?.items?.length || 0) === 0}
                >
                  Compare &amp; rank quotations
                </button>
              </div>

              <div className="commercial-section">
                <h4>Supplier quotes ({quotationsData?.items?.length || 0})</h4>
                {(quotationsData?.items?.length || 0) === 0 ? (
                  <p className="muted">No quotations yet. Agent 4 extracts quotes from RFQ responses.</p>
                ) : (
                  <div className="quotes-grid">
                    {quotationsData?.items?.map((quote: any, idx: number) => (
                      <div key={quote.quotation_id || idx} className="quote-card">
                        <div className="quote-card-head">
                          <strong>{quote.supplier_name || quote.supplier_id}</strong>
                          <span className="quote-price">
                            ${quote.total_cost_usd?.toLocaleString() || quote.amount || "—"}
                          </span>
                        </div>
                        <p className="muted tight">
                          Delivery: {quote.delivery_days || 7} days · Warranty:{" "}
                          {quote.warranty_months || 12} mo
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {comparisonResult && (
                <div className="commercial-section comparison-box">
                  <h4>Quotation evaluation</h4>
                  <div className="winner-banner">
                    Recommended: <strong>{comparisonResult.winner_quotation_id || "Optimal vendor"}</strong>
                  </div>
                  <p className="explanation-text">{comparisonResult.explanation}</p>
                </div>
              )}

              <div className="commercial-section">
                <h4>Purchase orders ({poData?.items?.length || 0})</h4>
                {(poData?.items?.length || 0) === 0 ? (
                  <p className="muted">No purchase orders for this process yet.</p>
                ) : (
                  <ul className="po-list">
                    {poData?.items?.map((po: any, idx: number) => (
                      <li key={po.id || idx} className="po-item">
                        <div>
                          <strong>PO #{po.po_number || po.id?.slice(0, 8)}</strong>
                          <span className="muted">
                            {" "}
                            · ${po.amount_total?.toLocaleString()} {po.currency_code || "USD"}
                          </span>
                        </div>
                        <div className="po-actions">
                          <span className={`status-tag ${po.status}`}>{po.status}</span>
                          {po.status === "draft" && (
                            <button
                              type="button"
                              className="btn btn-sm btn-success"
                              onClick={() => {
                                void runAction(
                                  "submit-po",
                                  () =>
                                    apiClient.submitPurchaseOrder(po.id, {
                                      process_id: process.id,
                                      idempotency_key: `po-sub-${Date.now()}`,
                                    }),
                                  "Purchase order submitted.",
                                );
                              }}
                            >
                              Submit PO
                            </button>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}

          {activeTab === "playground" && (
            <div className="playground-tab">
              <div className="playground-form agent4-panel">
                <div className="form-group">
                  <label htmlFor="tool-select">Allowlisted tool</label>
                  <select
                    id="tool-select"
                    value={selectedTool}
                    onChange={(e) => setSelectedTool(e.target.value)}
                    className="form-control"
                  >
                    {(toolsCatalog.length ? toolsCatalog : [{ name: selectedTool, risk_level: "medium", side_effect_status: "unknown" }]).map(
                      (t: any) => (
                        <option key={t.name} value={t.name}>
                          {t.name} — {t.risk_level} risk
                        </option>
                      ),
                    )}
                  </select>
                </div>

                <div className="form-group">
                  <label htmlFor="tool-args">Arguments (JSON)</label>
                  <textarea
                    id="tool-args"
                    value={playgroundArgs}
                    onChange={(e) => setPlaygroundArgs(e.target.value)}
                    rows={8}
                    className="form-control code-font"
                  />
                </div>

                <div className="playground-actions">
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={handlePlaygroundInvoke}
                    disabled={busy !== null}
                  >
                    Invoke through gateway
                  </button>
                </div>
              </div>

              {toolResult && (
                <div className="tool-result-card agent4-panel">
                  <span className="eyebrow">Result</span>
                  <pre className="code-block">{JSON.stringify(toolResult, null, 2)}</pre>
                </div>
              )}
            </div>
          )}

          {activeTab === "artifacts" && (
            <div className="artifacts-tab">
              <div className="artifacts-grid">
                <div className="artifact-box">
                  <h4>Email outbox ({execution?.email_outbox?.length || 0})</h4>
                  {!execution?.email_outbox?.length ? (
                    <p className="muted">No emails dispatched.</p>
                  ) : (
                    <ul className="mini-artifact-list">
                      {execution.email_outbox.map((e: any, idx: number) => (
                        <li key={e.id || idx}>
                          <strong>{e.subject || "(no subject)"}</strong>
                          <p className="muted tight">
                            To: {(e.to || []).join?.(", ") || e.to} [{e.status || "sent"}]
                          </p>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="artifact-box">
                  <h4>Documents ({execution?.generated_documents?.length || 0})</h4>
                  {!execution?.generated_documents?.length ? (
                    <p className="muted">No documents produced.</p>
                  ) : (
                    <ul className="mini-artifact-list">
                      {execution.generated_documents.map((d: any, idx: number) => (
                        <li key={d.id || idx}>
                          <strong>{d.title || "Document"}</strong>
                          <span className="muted"> · {d.doc_type || "memo"}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="artifact-box">
                  <h4>Calendar ({execution?.calendar_events?.length || 0})</h4>
                  {!execution?.calendar_events?.length ? (
                    <p className="muted">No meetings scheduled.</p>
                  ) : (
                    <ul className="mini-artifact-list">
                      {execution.calendar_events.map((c: any, idx: number) => (
                        <li key={c.id || idx}>
                          <strong>{c.title}</strong>
                          <p className="muted tight">{c.start_at}</p>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="artifact-box">
                  <h4>Tasks &amp; notifications</h4>
                  <p className="muted tight">
                    Tasks: {execution?.tasks?.length || 0} · Notifications:{" "}
                    {execution?.notifications?.length || 0}
                  </p>
                  <ul className="mini-artifact-list">
                    {(execution?.tasks || []).map((t: any, idx: number) => (
                      <li key={t.id || idx}>
                        <strong>{t.title}</strong>
                      </li>
                    ))}
                    {(execution?.notifications || []).map((n: any, idx: number) => (
                      <li key={n.id || idx}>
                        <strong>{n.title}</strong>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}
        </main>

        {reportModalOpen && reportData && (
          <div className="report-submodal-overlay" role="dialog" aria-modal="true">
            <div className="report-submodal">
              <header className="report-submodal-header">
                <h3>Execution audit summary</h3>
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => setReportModalOpen(false)}>
                  Close
                </button>
              </header>
              <div className="report-submodal-content">
                <div className="kpi-band">
                  <div>
                    <dt>Total tools</dt>
                    <dd>{reportData.tools_invoked_total}</dd>
                  </div>
                  <div>
                    <dt>Successful</dt>
                    <dd className="tone-success-text">{reportData.tools_successful}</dd>
                  </div>
                  <div>
                    <dt>Failed</dt>
                    <dd className="tone-danger-text">{reportData.tools_failed}</dd>
                  </div>
                  <div>
                    <dt>Documents</dt>
                    <dd>{reportData.generated_documents_count}</dd>
                  </div>
                </div>
                <pre className="code-block" style={{ maxHeight: "250px" }}>
                  {JSON.stringify(reportData, null, 2)}
                </pre>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
