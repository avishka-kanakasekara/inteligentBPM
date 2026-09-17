import { useState, useEffect, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ProcessSummary } from "@bpm/frontend-types";
import { ApiError, apiClient } from "../../lib/apiClient";

type HubTab = "overview" | "propose" | "commercial" | "playground" | "artifacts";
type ExecutionMode = "autonomous" | "step" | "dry_run";

interface Agent4ExecutionHubProps {
  process: ProcessSummary;
  onClose?: () => void;
  onRefreshParent?: () => void;
}

export function Agent4ExecutionHub({ process, onClose, onRefreshParent }: Agent4ExecutionHubProps) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<HubTab>("overview");
  const [mode, setMode] = useState<ExecutionMode>("autonomous");
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ text: string; type: "info" | "success" | "error" } | null>(null);
  
  // Execution report & comparison state
  const [reportModalOpen, setReportModalOpen] = useState(false);
  const [reportData, setReportData] = useState<any | null>(null);
  const [comparisonResult, setComparisonResult] = useState<any | null>(null);

  // Proposal state
  const [proposal, setProposal] = useState<any | null>(null);

  // Tool Playground state
  const [selectedTool, setSelectedTool] = useState<string>("notification.send");
  const [playgroundArgs, setPlaygroundArgs] = useState<string>(
    JSON.stringify({ title: "Update", body: "Process update notice", idempotency_key: `notif-${Date.now()}` }, null, 2)
  );
  const [toolResult, setToolResult] = useState<any | null>(null);

  // Fetch live execution state
  const { data: execution, refetch: refetchExecution } = useQuery({
    queryKey: ["agent4-execution", process.id],
    queryFn: () => apiClient.getExecution(process.id),
    refetchInterval: busy ? 3000 : 10000,
  });

  // Fetch tools catalog
  const { data: toolsCatalog = [] } = useQuery({
    queryKey: ["tools-catalog"],
    queryFn: () => apiClient.listTools(),
    staleTime: 60000,
  });

  // Fetch quotations & purchase orders
  const { data: quotationsData, refetch: refetchQuotations } = useQuery({
    queryKey: ["process-quotations", process.id],
    queryFn: () => apiClient.listQuotations(process.id),
  });

  const { data: poData, refetch: refetchPOs } = useQuery({
    queryKey: ["process-pos", process.id],
    queryFn: () => apiClient.listPurchaseOrders(process.id),
  });

  // Default templates for playground
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
        return JSON.stringify({
          supplier_id: "sup-001",
          product_sku: "LAPTOP-X",
          quantity: 5,
          subject: "RFQ: 5x Laptop X",
          body: "Please provide your formal quote.",
          idempotency_key: `rfq-${ts}`,
        }, null, 2);
      case "email.create_draft":
      case "email.send":
        return JSON.stringify({
          to_employee_id: "casey@acme.test",
          subject: "Process Authorization Notice",
          body: "Your procurement order has been reviewed.",
          idempotency_key: `email-${ts}`,
        }, null, 2);
      case "notification.send":
        return JSON.stringify({
          title: "Execution Update",
          body: "Process step reached checkpoint.",
          idempotency_key: `notif-${ts}`,
        }, null, 2);
      case "calendar.create_event":
        return JSON.stringify({
          title: "Procurement Review Meeting",
          start_at: new Date(Date.now() + 86400000).toISOString(),
          attendees: ["casey@acme.test"],
          description: "Review supplier terms",
          idempotency_key: `cal-${ts}`,
        }, null, 2);
      case "task.assign":
        return JSON.stringify({
          title: "Inspect Received Equipment",
          assignee_id: "emp-001",
          description: "Verify delivery matches PO",
          idempotency_key: `task-${ts}`,
        }, null, 2);
      case "document.generate":
        return JSON.stringify({
          title: "Procurement Summary Memo",
          doc_type: "memo",
          content: "Comprehensive overview of laptop acquisition and vendor selection.",
          idempotency_key: `doc-${ts}`,
        }, null, 2);
      case "quotation.compare":
        return JSON.stringify({
          quotation_ids: ["quote-001", "quote-002"],
          explain: true,
        }, null, 2);
      default:
        return JSON.stringify({ idempotency_key: `tool-${ts}` }, null, 2);
    }
  }, []);

  useEffect(() => {
    setPlaygroundArgs(getToolTemplate(selectedTool));
  }, [selectedTool, getToolTemplate]);

  // Load next proposal
  const loadProposal = useCallback(async () => {
    try {
      const res = await apiClient.proposeExecutionAction(process.id, execution?.process_run_id);
      setProposal(res);
    } catch {
      setProposal(null);
    }
  }, [process.id, execution?.process_run_id]);

  useEffect(() => {
    if (activeTab === "propose") {
      void loadProposal();
    }
  }, [activeTab, loadProposal]);

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
      const msg = err instanceof ApiError ? `${err.message} (${err.code || "ERROR"})` : err?.message || "Action failed";
      setNotice({ text: msg, type: "error" });
    } finally {
      setBusy(null);
    }
  };

  const handleStartOrAdvance = () => {
    const isDry = mode === "dry_run";
    const isAuto = mode === "autonomous";
    const steps = isAuto ? 20 : 1;

    if (!execution || execution.status === "not_run" || execution.status === "draft") {
      runAction(
        "start",
        () => apiClient.startExecution(process.id, {
          dry_run: isDry,
          auto_run: isAuto,
          max_steps: steps,
        }),
        isDry ? "Dry-run simulation started." : isAuto ? "Autonomous run completed." : "Advanced 1 step."
      );
    } else {
      runAction(
        "advance",
        () => apiClient.advanceExecution(process.id, steps),
        isAuto ? "Autonomous run advanced." : "Advanced 1 step."
      );
    }
  };

  const handlePause = () => {
    runAction("pause", () => apiClient.pauseExecution(process.id), "Execution paused.");
  };

  const handleResume = () => {
    runAction("resume", () => apiClient.resumeExecution(process.id), "Execution resumed.");
  };

  const handleCancel = () => {
    if (!window.confirm("Cancel this execution run? This will abort all pending steps.")) return;
    runAction("cancel", () => apiClient.cancelExecution(process.id), "Execution cancelled.");
  };

  const handleReset = () => {
    if (!window.confirm("Reset execution run back to initial step?")) return;
    runAction("reset", () => apiClient.resetExecution(process.id), "Execution reset to start.");
  };

  const handleExecuteProposal = () => {
    if (!proposal) return;
    runAction(
      "proposal",
      () => apiClient.invokeTool(process.id, proposal.tool_name, proposal.arguments || {}, execution?.process_run_id),
      `Executed ${proposal.tool_name}`
    );
  };

  const handlePlaygroundInvoke = () => {
    let parsed: Record<string, unknown> = {};
    try {
      parsed = JSON.parse(playgroundArgs);
    } catch {
      setNotice({ text: "Invalid JSON in arguments.", type: "error" });
      return;
    }
    runAction(
      "playground",
      async () => {
        const res = await apiClient.invokeTool(process.id, selectedTool, parsed, execution?.process_run_id);
        setToolResult(res);
        return res;
      },
      `Tool ${selectedTool} executed successfully.`
    );
  };

  const handleCompareQuotations = async () => {
    const quotes = quotationsData?.items || [];
    if (quotes.length < 1) {
      setNotice({ text: "No quotations available to compare.", type: "info" });
      return;
    }
    const ids = quotes.map((q: any) => q.quotation_id || q.id);
    runAction(
      "compare-quotes",
      async () => {
        const res = await apiClient.compareQuotations(process.id, ids, true);
        setComparisonResult(res);
        return res;
      },
      "Quotations analyzed with AI scoring."
    );
  };

  const handleOpenReport = async () => {
    try {
      const rep = await apiClient.getExecutionReport(process.id, execution?.process_run_id);
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

  return (
    <div className="agent4-hub-modal-overlay" role="dialog" aria-labelledby="agent4-hub-title" aria-modal="true">
      <div className="agent4-hub-container">
        {/* Header */}
        <header className="agent4-hub-header">
          <div className="agent4-hub-header-left">
            <div className="agent4-badge-cluster">
              <span className="agent-number-badge">Agent 4</span>
              <span className={`status-pill ${
                isExecuting ? "tone-info" :
                isPaused ? "tone-warning" :
                isAwaiting ? "tone-warning" :
                runStatus === "completed" ? "tone-success" :
                runStatus === "cancelled" ? "tone-danger" : "tone-neutral"
              }`}>
                {runStatus.toUpperCase().replace("_", " ")}
              </span>
              {execution?.dry_run && <span className="status-pill tone-warning">SIMULATION (DRY RUN)</span>}
            </div>
            <h2 id="agent4-hub-title">{process.name}</h2>
            <p className="muted tight">Controlled Autonomous Execution & Tool Gateway</p>
          </div>

          <div className="agent4-hub-header-right">
            <button type="button" className="btn btn-sm btn-ghost" onClick={handleOpenReport}>
              📄 Audit Report
            </button>
            {onClose && (
              <button type="button" className="btn btn-sm btn-ghost close-btn" onClick={onClose} aria-label="Close modal">
                ✕
              </button>
            )}
          </div>
        </header>

        {/* Notices */}
        {notice && (
          <div className={`agent4-notice ${notice.type}`} role="status">
            <span>{notice.text}</span>
            <button type="button" className="dismiss-btn" onClick={() => setNotice(null)}>✕</button>
          </div>
        )}

        {/* Mode Selector & Main Control Bar */}
        <div className="agent4-control-bar">
          <div className="mode-toggle-group" role="group" aria-label="Execution mode">
            <span className="mode-label">Mode:</span>
            <button
              type="button"
              className={`mode-btn ${mode === "autonomous" ? "is-active" : ""}`}
              onClick={() => setMode("autonomous")}
              disabled={isExecuting}
            >
              ⚡ Autonomous (Auto-Run)
            </button>
            <button
              type="button"
              className={`mode-btn ${mode === "step" ? "is-active" : ""}`}
              onClick={() => setMode("step")}
              disabled={isExecuting}
            >
              🎯 Supervised (Step-by-Step)
            </button>
            <button
              type="button"
              className={`mode-btn ${mode === "dry_run" ? "is-active" : ""}`}
              onClick={() => setMode("dry_run")}
              disabled={isExecuting}
            >
              🧪 Dry-Run (Sandbox)
            </button>
          </div>

          <div className="action-buttons-group">
            {!isTerminal && (
              <>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={busy !== null || isExecuting}
                  onClick={handleStartOrAdvance}
                >
                  {busy === "start" || busy === "advance" ? "Running…" :
                    mode === "autonomous" ? "⚡ Run All Steps" :
                    mode === "dry_run" ? "🧪 Simulate Run" : "🎯 Step Forward (1 Tool)"}
                </button>

                {isExecuting && (
                  <button type="button" className="btn btn-warning" onClick={handlePause} disabled={busy !== null}>
                    ⏸ Pause Run
                  </button>
                )}

                {(isPaused || isAwaiting) && (
                  <button type="button" className="btn btn-success" onClick={handleResume} disabled={busy !== null}>
                    ▶ Resume Run
                  </button>
                )}

                <button type="button" className="btn btn-ghost" onClick={handleCancel} disabled={busy !== null}>
                  🛑 Cancel
                </button>
              </>
            )}

            {isTerminal && (
              <button type="button" className="btn btn-ghost" onClick={handleReset} disabled={busy !== null}>
                🔄 Reset Run
              </button>
            )}
          </div>
        </div>

        {/* Tab Navigation */}
        <nav className="agent4-nav-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "overview"}
            className={activeTab === "overview" ? "is-active" : ""}
            onClick={() => setActiveTab("overview")}
          >
            📊 Execution Overview ({invocations.length} Tools)
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "propose"}
            className={activeTab === "propose" ? "is-active" : ""}
            onClick={() => setActiveTab("propose")}
          >
            🤖 Copilot Proposal {proposal ? "•" : ""}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "commercial"}
            className={activeTab === "commercial" ? "is-active" : ""}
            onClick={() => setActiveTab("commercial")}
          >
            💼 Quotations & POs ({quotationsData?.items?.length || 0})
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "playground"}
            className={activeTab === "playground" ? "is-active" : ""}
            onClick={() => setActiveTab("playground")}
          >
            🛠 Operator Tool Console ({toolsCatalog.length} Tools)
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "artifacts"}
            className={activeTab === "artifacts" ? "is-active" : ""}
            onClick={() => setActiveTab("artifacts")}
          >
            📦 Output Artifacts
          </button>
        </nav>

        {/* Tab Body */}
        <main className="agent4-tab-content">
          {/* TAB 1: OVERVIEW */}
          {activeTab === "overview" && (
            <div className="overview-tab">
              {/* Stepper Card */}
              <div className="stepper-card">
                <div className="stepper-header">
                  <div>
                    <span className="eyebrow">Execution Progress</span>
                    <h3>Current Step: #{currentStep + 1}</h3>
                  </div>
                  {execution?.pause_reason && (
                    <div className="pause-callout">
                      <strong>Pause Reason:</strong> {execution.pause_reason}
                    </div>
                  )}
                </div>

                <div className="tool-timeline">
                  {invocations.length === 0 ? (
                    <p className="muted">No tools invoked yet. Select a mode above and click Run to begin.</p>
                  ) : (
                    <ul className="timeline-list">
                      {invocations.map((inv: any, idx: number) => {
                        const isOk = inv.status === "executed" || inv.status === "replayed";
                        const isDry = inv.status === "dry_run";
                        return (
                          <li key={inv.id || idx} className="timeline-item">
                            <span className={`timeline-marker ${isOk ? "ok" : isDry ? "dry" : "failed"}`}>
                              {isOk ? "✓" : isDry ? "🧪" : "✕"}
                            </span>
                            <div className="timeline-details">
                              <div className="timeline-row">
                                <strong className="tool-code">{inv.tool_name}</strong>
                                <span className={`status-tag ${inv.status}`}>{inv.status}</span>
                                <time className="timestamp">{inv.created_at ? new Date(inv.created_at).toLocaleTimeString() : "—"}</time>
                              </div>
                              {inv.result?.data && (
                                <p className="timeline-summary">
                                  {inv.result.data.subject ? `Subject: ${inv.result.data.subject}` :
                                   inv.result.data.title ? `Title: ${inv.result.data.title}` :
                                   inv.result.data.product_sku ? `SKU: ${inv.result.data.product_sku} (Qty: ${inv.result.data.quantity})` :
                                   inv.result.data.id ? `ID: ${inv.result.data.id}` : "Executed with safe idempotency"}
                                </p>
                              )}
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

          {/* TAB 2: COPILOT PROPOSAL */}
          {activeTab === "propose" && (
            <div className="proposal-tab">
              <div className="proposal-card">
                <div className="proposal-header">
                  <span className="eyebrow">Gemini Reasoning Copilot</span>
                  <h3>Next Recommended Action</h3>
                  <button type="button" className="btn btn-sm btn-ghost" onClick={() => void loadProposal()}>
                    🔄 Re-evaluate
                  </button>
                </div>

                {proposal ? (
                  <div className="proposal-body">
                    <div className="proposal-meta-grid">
                      <div>
                        <span className="meta-label">Proposed Tool</span>
                        <code className="meta-tool">{proposal.tool_name}</code>
                      </div>
                      <div>
                        <span className="meta-label">Requires Human Approval</span>
                        <span className={`status-pill ${proposal.requires_approval ? "tone-warning" : "tone-success"}`}>
                          {proposal.requires_approval ? "YES (Blocked)" : "NO (Auto-executable)"}
                        </span>
                      </div>
                    </div>

                    <div className="proposal-rationale">
                      <span className="meta-label">AI Rationale:</span>
                      <p>{proposal.rationale || "Tool matches current plan step requirements."}</p>
                    </div>

                    {proposal.approval_reason && (
                      <div className="proposal-approval-warning">
                        <strong>Approval Condition:</strong> {proposal.approval_reason}
                      </div>
                    )}

                    <div className="proposal-args-preview">
                      <span className="meta-label">Proposed Arguments:</span>
                      <pre className="code-block">{JSON.stringify(proposal.arguments || {}, null, 2)}</pre>
                    </div>

                    <div className="proposal-actions">
                      <button
                        type="button"
                        className="btn btn-primary"
                        onClick={handleExecuteProposal}
                        disabled={busy !== null}
                      >
                        ✓ Approve & Execute This Step
                      </button>
                    </div>
                  </div>
                ) : (
                  <p className="muted">No active proposal available. Click Re-evaluate or run the next step.</p>
                )}
              </div>
            </div>
          )}

          {/* TAB 3: COMMERCIAL & QUOTATIONS */}
          {activeTab === "commercial" && (
            <div className="commercial-tab">
              <div className="commercial-actions-bar">
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={handleCompareQuotations}
                  disabled={busy !== null || (quotationsData?.items?.length || 0) === 0}
                >
                  ⚡ AI Compare & Rank Quotations
                </button>
              </div>

              {/* Quotations List */}
              <div className="commercial-section">
                <h4>Extracted Supplier Quotes ({quotationsData?.items?.length || 0})</h4>
                {(quotationsData?.items?.length || 0) === 0 ? (
                  <p className="muted">No quotations recorded. Agent 4 will extract quotes upon receiving RFQ responses.</p>
                ) : (
                  <div className="quotes-grid">
                    {quotationsData?.items?.map((quote: any, idx: number) => (
                      <div key={quote.quotation_id || idx} className="quote-card">
                        <div className="quote-card-head">
                          <strong>{quote.supplier_name || quote.supplier_id}</strong>
                          <span className="quote-price">${quote.total_cost_usd?.toLocaleString() || quote.amount || "—"}</span>
                        </div>
                        <p className="muted tight">Delivery: {quote.delivery_days || 7} days · Warranty: {quote.warranty_months || 12} mo</p>
                        <p className="muted tight">Compliance Score: {((quote.policy_compliance_score || 0.8) * 100).toFixed(0)}%</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Comparison Results */}
              {comparisonResult && (
                <div className="commercial-section comparison-box">
                  <h4>AI Quotation Evaluation & Recommendation</h4>
                  <div className="winner-banner">
                    🏆 Recommended Winner: <strong>{comparisonResult.winner_quotation_id || "Optimal Vendor"}</strong>
                  </div>
                  <p className="explanation-text">{comparisonResult.explanation}</p>
                  
                  {comparisonResult.scores && (
                    <div className="score-table-wrap">
                      <table className="mini-table">
                        <thead>
                          <tr>
                            <th>Quote</th>
                            <th>Cost Score</th>
                            <th>Delivery</th>
                            <th>Warranty</th>
                            <th>Overall</th>
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(comparisonResult.scores).map(([qid, sc]: [string, any]) => (
                            <tr key={qid} className={qid === comparisonResult.winner_quotation_id ? "winner-row" : ""}>
                              <td>{qid}</td>
                              <td>{sc.total_cost?.toFixed(1)}</td>
                              <td>{sc.delivery_time?.toFixed(1)}</td>
                              <td>{sc.warranty?.toFixed(1)}</td>
                              <td><strong>{sc.weighted_total?.toFixed(2)}</strong></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}

              {/* Purchase Orders */}
              <div className="commercial-section">
                <h4>Purchase Orders ({poData?.items?.length || 0})</h4>
                {(poData?.items?.length || 0) === 0 ? (
                  <p className="muted">No purchase orders generated for this process yet.</p>
                ) : (
                  <ul className="po-list">
                    {poData?.items?.map((po: any, idx: number) => (
                      <li key={po.id || idx} className="po-item">
                        <div>
                          <strong>PO #{po.po_number || po.id?.slice(0, 8)}</strong>
                          <span className="muted"> · ${po.amount_total?.toLocaleString()} {po.currency_code || "USD"}</span>
                        </div>
                        <div className="po-actions">
                          <span className={`status-tag ${po.status}`}>{po.status}</span>
                          {po.status === "draft" && (
                            <button
                              type="button"
                              className="btn btn-sm btn-success"
                              onClick={() => {
                                runAction(
                                  "submit-po",
                                  () => apiClient.submitPurchaseOrder(po.id, {
                                    process_id: process.id,
                                    idempotency_key: `po-sub-${Date.now()}`,
                                  }),
                                  "Purchase Order submitted."
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

          {/* TAB 4: PLAYGROUND */}
          {activeTab === "playground" && (
            <div className="playground-tab">
              <div className="playground-form">
                <div className="form-group">
                  <label htmlFor="tool-select">Select Allowlisted Tool</label>
                  <select
                    id="tool-select"
                    value={selectedTool}
                    onChange={(e) => setSelectedTool(e.target.value)}
                    className="form-control"
                  >
                    {toolsCatalog.map((t: any) => (
                      <option key={t.name} value={t.name}>
                        {t.name} — ({t.risk_level} risk, {t.side_effect_status})
                      </option>
                    ))}
                  </select>
                </div>

                <div className="form-group">
                  <label htmlFor="tool-args">Tool Arguments (JSON)</label>
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
                    ⚡ Invoke Tool Through Gateway
                  </button>
                </div>
              </div>

              {toolResult && (
                <div className="tool-result-card">
                  <span className="eyebrow">Execution Result</span>
                  <pre className="code-block">{JSON.stringify(toolResult, null, 2)}</pre>
                </div>
              )}
            </div>
          )}

          {/* TAB 5: ARTIFACTS */}
          {activeTab === "artifacts" && (
            <div className="artifacts-tab">
              <div className="artifacts-grid">
                {/* Emails */}
                <div className="artifact-box">
                  <h4>Email Outbox ({execution?.email_outbox?.length || 0})</h4>
                  {(!execution?.email_outbox || execution.email_outbox.length === 0) ? (
                    <p className="muted">No emails dispatched.</p>
                  ) : (
                    <ul className="mini-artifact-list">
                      {execution.email_outbox.map((e: any, idx: number) => (
                        <li key={e.id || idx}>
                          <strong>{e.subject || "(no subject)"}</strong>
                          <p className="muted tight">To: {(e.to || []).join?.(", ") || e.to} [{e.status || "sent"}]</p>
                          <p className="preview-text">{String(e.body || "").slice(0, 150)}</p>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                {/* Generated Documents */}
                <div className="artifact-box">
                  <h4>Generated Documents ({execution?.generated_documents?.length || 0})</h4>
                  {(!execution?.generated_documents || execution.generated_documents.length === 0) ? (
                    <p className="muted">No documents produced.</p>
                  ) : (
                    <ul className="mini-artifact-list">
                      {execution.generated_documents.map((d: any, idx: number) => (
                        <li key={d.id || idx}>
                          <strong>{d.title || "Document"}</strong>
                          <span className="muted"> · {d.doc_type || "memo"}</span>
                          <p className="preview-text">{String(d.content || d.summary || "").slice(0, 150)}</p>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                {/* Calendar */}
                <div className="artifact-box">
                  <h4>Calendar Events ({execution?.calendar_events?.length || 0})</h4>
                  {(!execution?.calendar_events || execution.calendar_events.length === 0) ? (
                    <p className="muted">No meetings scheduled.</p>
                  ) : (
                    <ul className="mini-artifact-list">
                      {execution.calendar_events.map((c: any, idx: number) => (
                        <li key={c.id || idx}>
                          <strong>{c.title}</strong>
                          <p className="muted tight">{c.start_at} · {(c.attendees || []).join(", ")}</p>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                {/* Tasks & Notifications */}
                <div className="artifact-box">
                  <h4>Tasks & Notifications</h4>
                  <p className="muted tight">Tasks: {execution?.tasks?.length || 0} · Notifications: {execution?.notifications?.length || 0}</p>
                  <ul className="mini-artifact-list">
                    {(execution?.tasks || []).map((t: any, idx: number) => (
                      <li key={t.id || idx}>
                        <strong>Task: {t.title}</strong>
                        <span className="muted"> → {t.assignee_name || t.assignee_id}</span>
                      </li>
                    ))}
                    {(execution?.notifications || []).map((n: any, idx: number) => (
                      <li key={n.id || idx}>
                        <strong>Notice: {n.title}</strong>
                        <p className="muted tight">{n.body || n.summary}</p>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}
        </main>

        {/* Report Modal */}
        {reportModalOpen && reportData && (
          <div className="report-submodal-overlay" role="dialog" aria-modal="true">
            <div className="report-submodal">
              <header className="report-submodal-header">
                <h3>Execution Audit Summary</h3>
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => setReportModalOpen(false)}>
                  ✕ Close
                </button>
              </header>
              <div className="report-submodal-content">
                <div className="kpi-band">
                  <div>
                    <dt>Total Tools</dt>
                    <dd>{reportData.tools_invoked_total}</dd>
                  </div>
                  <div>
                    <dt>Successful</dt>
                    <dd className="tone-success-text">{reportData.tools_successful}</dd>
                  </div>
                  <div>
                    <dt>Failed/Denied</dt>
                    <dd className="tone-danger-text">{reportData.tools_failed}</dd>
                  </div>
                  <div>
                    <dt>Documents</dt>
                    <dd>{reportData.generated_documents_count}</dd>
                  </div>
                </div>

                <div className="audit-hashes">
                  <p><strong>Plan Snapshot Hash:</strong> <code>{reportData.plan_snapshot_hash || "n/a"}</code></p>
                  <p><strong>Risk Snapshot Hash:</strong> <code>{reportData.risk_snapshot_hash || "n/a"}</code></p>
                  <p><strong>Generated At:</strong> {new Date(reportData.generated_at).toLocaleString()}</p>
                </div>

                <pre className="code-block" style={{ maxHeight: "250px" }}>
                  {JSON.stringify(reportData, null, 2)}
                </pre>
              </div>
              <footer className="report-submodal-footer">
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => {
                    navigator.clipboard.writeText(JSON.stringify(reportData, null, 2));
                    setNotice({ text: "Report JSON copied to clipboard.", type: "success" });
                  }}
                >
                  📋 Copy JSON to Clipboard
                </button>
              </footer>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
