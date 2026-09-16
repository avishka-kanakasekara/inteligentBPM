import { useCallback, useEffect, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import type { ProcessSummary } from "@bpm/frontend-types";
import { ApiError, apiClient } from "../../lib/apiClient";
import {
  ApprovalBadge,
  ExecutionBadge,
  ProcessStatusBadge,
  RiskBadge,
} from "./StatusBadges";

type ActionKey = "allocate" | "risk" | "approval" | "execute";

type AgentDetails = {
  allocation: string | null;
  risk: string | null;
  execution: string | null;
};

type ExecutionArtifacts = {
  documents: any[];
  calendar: any[];
  tasks: any[];
  notifications: any[];
  emails: any[];
};

function emptyArtifacts(): ExecutionArtifacts {
  return { documents: [], calendar: [], tasks: [], notifications: [], emails: [] };
}

function extractArtifacts(data: any): ExecutionArtifacts {
  if (!data) return emptyArtifacts();
  return {
    documents: Array.isArray(data.generated_documents) ? data.generated_documents : [],
    calendar: Array.isArray(data.calendar_events) ? data.calendar_events : [],
    tasks: Array.isArray(data.tasks) ? data.tasks : [],
    notifications: Array.isArray(data.notifications) ? data.notifications : [],
    emails: Array.isArray(data.email_outbox) ? data.email_outbox : [],
  };
}

function summarizeAllocation(data: any): string | null {
  if (!data || data.status === "not_run") return null;
  const status = data.status ?? "unknown";
  const assignments = data.assignments ?? data.result?.assignments ?? [];
  const unresolved = data.unresolved ?? data.result?.unresolved ?? [];
  const candidates = data.candidates ?? data.result?.candidates ?? [];
  const peopleTypes = new Set([
    "employee",
    "manager",
    "approval_authority",
    "supplier",
    "supplier_contact",
    "department",
    "budget",
    "cost_center",
  ]);
  const people = Array.isArray(assignments)
    ? assignments.filter((a: any) => peopleTypes.has(String(a.resource_type || "")))
    : [];
  const integrations = Array.isArray(assignments)
    ? assignments.filter((a: any) => String(a.resource_type || "") === "integration")
    : [];
  const lines: string[] = [
    `Status: ${status}`,
    `LLM assist: ${data.llm_used ? "yes" : "no"}`,
  ];
  if (people.length) {
    lines.push(`People & suppliers (${people.length}):`);
    for (const a of people.slice(0, 16)) {
      const role = a.requirement || a.required_resource || a.role || a.resource_type || "resource";
      const name =
        a.display_name ||
        a.resolved_name ||
        a.employee_name ||
        a.supplier_name ||
        a.candidate_name ||
        a.resource_id ||
        "unbound";
      const kind = a.resource_type ? ` (${a.resource_type})` : "";
      lines.push(`• ${role} → ${name}${kind}`);
      if (a.reason) lines.push(`    reason: ${a.reason}`);
    }
    if (people.length > 16) lines.push(`• …and ${people.length - 16} more`);
  } else if (Array.isArray(assignments) && assignments.length) {
    lines.push("No people/suppliers assigned yet.");
  } else {
    lines.push("No concrete assignments yet.");
  }
  if (integrations.length) {
    lines.push(`Systems/integrations: ${integrations.length} bound`);
  }
  const blocking = Array.isArray(unresolved)
    ? unresolved.filter((u: any) => (typeof u === "object" ? u.blocking !== false : true))
    : [];
  if (blocking.length) {
    lines.push(`Still unresolved (${blocking.length}):`);
    for (const u of blocking.slice(0, 6)) {
      const reason =
        typeof u === "string" ? u : u.requirement || u.question || u.reason || u.message || JSON.stringify(u);
      lines.push(`• ${reason}`);
    }
  }
  if (Array.isArray(candidates) && candidates.length && !people.length) {
    lines.push(`Top candidates (${Math.min(candidates.length, 5)}):`);
    for (const c of candidates.slice(0, 5)) {
      lines.push(`• ${c.display_name || c.resource_id} (${c.resource_type || "resource"})`);
    }
  }
  if (data.reasoning_summary) lines.push(`Notes: ${data.reasoning_summary}`);
  return lines.join("\n");
}

function summarizeRisk(data: any): string | null {
  if (!data || data.overall_status === "not_run") return null;
  const decision = data.decision ?? data.result?.decision ?? "unknown";
  const items = data.risk_items ?? data.result?.risk_items ?? [];
  const blocking = data.blocking_issues ?? data.result?.blocking_issues ?? [];
  const roles = data.required_approver_roles ?? data.result?.required_approver_roles ?? [];
  const lines: string[] = [`Decision: ${decision}`];
  if (Array.isArray(roles) && roles.length) {
    lines.push(`Required approvers: ${roles.join(", ")}`);
  }
  if (data.reasoning_summary) lines.push(`Summary: ${data.reasoning_summary}`);
  if (Array.isArray(items) && items.length) {
    lines.push("Risk items:");
    for (const item of items.slice(0, 6)) {
      const sev = item.severity || "medium";
      const desc = item.description || item.id || "risk";
      lines.push(`• [${sev}] ${desc}${item.blocking ? " (blocking)" : ""}`);
    }
  }
  if (Array.isArray(blocking) && blocking.length) {
    lines.push("Blocking issues:");
    for (const b of blocking.slice(0, 4)) {
      lines.push(`• ${b.description || b.id || JSON.stringify(b)}`);
    }
  }
  return lines.join("\n");
}

function summarizeExecution(data: any): string | null {
  if (!data || data.status === "not_run") return null;
  const status = data.status ?? data.run?.status ?? "unknown";
  const dry = data.dry_run ?? data.run?.dry_run;
  const lines: string[] = [`Run status: ${status}${dry ? " (dry run)" : " (live)"}`];
  const tools = data.invocations ?? data.tool_invocations ?? data.recent_tools ?? [];
  if (Array.isArray(tools) && tools.length) {
    lines.push(`Tools executed (${tools.length}):`);
    for (const t of tools.slice(0, 12)) {
      const name = t.tool_name || t.name || "tool";
      const st = t.status || "done";
      const dataObj = t.result?.data || t.data || {};
      let detail = "";
      if (name.startsWith("email.") || name === "supplier.request_quote" || name === "notification.send") {
        const to = Array.isArray(dataObj.to) ? dataObj.to.join(", ") : dataObj.to;
        if (to || dataObj.subject) detail = ` → ${to || "?"} | ${dataObj.subject || ""}`;
      } else if (name === "calendar.create_event") {
        detail = ` → ${dataObj.title || "event"} (${(dataObj.attendees || []).length} attendees)`;
      } else if (name === "task.assign") {
        detail = ` → ${dataObj.assignee_name || dataObj.assignee_id || "?"} | ${dataObj.title || ""}`;
      } else if (name === "document.generate") {
        detail = ` → ${dataObj.title || dataObj.doc_type || "doc"}`;
      } else if (name.startsWith("purchase_order.")) {
        detail = ` → ${dataObj.po_number || dataObj.external_ref || dataObj.id || ""}`;
      } else if (dataObj.id) {
        detail = ` → ${dataObj.id}`;
      }
      const mock = dataObj.mock === false ? " [live]" : dataObj.mock ? " [mock]" : "";
      lines.push(`• ${name} [${st}]${detail}${mock}`);
      if (dataObj.body) {
        const preview = String(dataObj.body).replace(/\s+/g, " ").slice(0, 120);
        lines.push(`    body: ${preview}${String(dataObj.body).length > 120 ? "…" : ""}`);
      }
    }
  } else if (data.pause_reason) {
    lines.push(`Paused: ${data.pause_reason}`);
  } else {
    lines.push("No tool invocations recorded yet.");
  }
  const emails = data.email_outbox || [];
  if (Array.isArray(emails) && emails.length) {
    lines.push(`Emails sent/drafted (${emails.length}):`);
    for (const e of emails.slice(0, 5)) {
      lines.push(
        `• [${e.status || "sent"}] ${(e.to || []).join?.(", ") || e.to || "?"} — ${e.subject || "(no subject)"}`,
      );
    }
  }
  if (data.current_step_index != null) {
    lines.push(`Current step index: ${data.current_step_index}`);
  }
  if (data.pause_reason) lines.push(`Pause reason: ${data.pause_reason}`);
  return lines.join("\n");
}

export function ProcessStatusCard({ process }: { process: ProcessSummary }) {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState<ActionKey | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [details, setDetails] = useState<AgentDetails>({
    allocation: null,
    risk: null,
    execution: null,
  });
  const [artifacts, setArtifacts] = useState<ExecutionArtifacts>(emptyArtifacts());
  const [openDocId, setOpenDocId] = useState<string | null>(null);
  const [localPresence, setLocalPresence] = useState({
    allocation: false,
    risk: false,
    execution: false,
  });
  const [showDetails, setShowDetails] = useState(true);

  const wantAllocation = Boolean(process.has_allocation || localPresence.allocation);
  const wantRisk = Boolean(process.has_risk || localPresence.risk);
  const wantExecution = Boolean(process.has_execution || localPresence.execution);

  const refreshDetails = useCallback(async () => {
    const next: AgentDetails = { allocation: null, risk: null, execution: null };
    // Only fetch stages that already ran — avoids noisy 404s for draft processes.
    if (wantAllocation) {
      try {
        next.allocation = summarizeAllocation(await apiClient.getAllocation(process.id));
      } catch {
        next.allocation = null;
      }
    }
    if (wantRisk) {
      try {
        next.risk = summarizeRisk(await apiClient.getRisk(process.id));
      } catch {
        next.risk = null;
      }
    }
    if (wantExecution) {
      try {
        const exec = await apiClient.getExecution(process.id);
        next.execution = summarizeExecution(exec);
        setArtifacts(extractArtifacts(exec));
      } catch {
        next.execution = null;
        setArtifacts(emptyArtifacts());
      }
    } else {
      setArtifacts(emptyArtifacts());
    }
    setDetails(next);
  }, [wantAllocation, wantExecution, wantRisk, process.id]);

  useEffect(() => {
    void refreshDetails();
  }, [refreshDetails]);

  async function runAction(key: ActionKey, fn: () => Promise<unknown>, success: string) {
    setBusy(key);
    setNotice(`Running ${key}…`);
    try {
      const result = await fn();
      if (key === "allocate") {
        setLocalPresence((p) => ({ ...p, allocation: true }));
        setDetails((d) => ({ ...d, allocation: summarizeAllocation(result) }));
      }
      if (key === "risk") {
        setLocalPresence((p) => ({ ...p, risk: true }));
        setDetails((d) => ({ ...d, risk: summarizeRisk(result) }));
      }
      if (key === "execute") {
        setLocalPresence((p) => ({ ...p, execution: true }));
        setDetails((d) => ({ ...d, execution: summarizeExecution(result) }));
        setArtifacts(extractArtifacts(result));
        void queryClient.invalidateQueries({ queryKey: ["generated-documents"] });
        void queryClient.invalidateQueries({ queryKey: ["calendar-events"] });
        void queryClient.invalidateQueries({ queryKey: ["tasks"] });
        void queryClient.invalidateQueries({ queryKey: ["workspace-notifications"] });
        void queryClient.invalidateQueries({ queryKey: ["emails"] });
      }
      setNotice(success);
      setShowDetails(true);
      void queryClient.invalidateQueries({ queryKey: ["processes"] });
    } catch (err: unknown) {
      const message =
        err instanceof ApiError
          ? `${err.message}${err.code ? ` (${err.code})` : ""}`
          : err instanceof Error
            ? err.message
            : "Request failed";
      setNotice(message);
      alert(message);
    } finally {
      setBusy(null);
    }
  }

  const disabled = busy !== null;

  return (
    <article className="process-card" aria-labelledby={`process-${process.id}`}>
      <header className="process-card-header">
        <h3 id={`process-${process.id}`}>{process.name}</h3>
        <div className="badge-row">
          <ProcessStatusBadge status={process.status} />
          <RiskBadge level={process.risk_level} />
          <ApprovalBadge status={process.approval_status} />
          <ExecutionBadge status={process.execution_status} />
        </div>
      </header>

      <dl className="process-meta">
        <div>
          <dt>Missing information</dt>
          <dd>
            {process.missing_information.length
              ? process.missing_information.join("; ")
              : "None"}
          </dd>
        </div>
        <div>
          <dt>Unresolved assignments</dt>
          <dd>
            {process.unresolved_assignments.length
              ? process.unresolved_assignments.join("; ")
              : "None"}
          </dd>
        </div>
        <div>
          <dt>Policy evidence</dt>
          <dd>
            {process.policy_evidence.length ? process.policy_evidence.join("; ") : "None"}
          </dd>
        </div>
        <div>
          <dt>Source references</dt>
          <dd>
            {process.source_refs.length
              ? process.source_refs.map((ref) => ref.label).join("; ")
              : "None"}
          </dd>
        </div>
        <div>
          <dt>Agent recommendations</dt>
          <dd>
            {process.recommendations.length ? process.recommendations.join("; ") : "None"}
          </dd>
        </div>
        <div>
          <dt>Human decision</dt>
          <dd>{process.human_decision ?? "Pending"}</dd>
        </div>
      </dl>

      <div style={{ marginTop: "1rem" }}>
        <button
          type="button"
          onClick={() => setShowDetails((v) => !v)}
          style={{
            ...ghostBtn,
            marginBottom: "0.5rem",
          }}
        >
          {showDetails ? "Hide agent activity" : "Show agent activity"}
        </button>
        {showDetails ? (
          <div
            style={{
              display: "grid",
              gap: "0.75rem",
              background: "rgba(31, 111, 74, 0.04)",
              border: "1px solid var(--line, #c3d0c2)",
              borderRadius: "8px",
              padding: "0.85rem 1rem",
            }}
          >
            <section>
              <h4 style={{ margin: "0 0 0.35rem", fontSize: "0.9rem" }}>
                Agent 2 — Resource allocation
              </h4>
              <pre style={detailPre}>
                {details.allocation ??
                  "Not run yet. Assigns people, departments, and suppliers from the org directory."}
              </pre>
            </section>
            <section>
              <h4 style={{ margin: "0 0 0.35rem", fontSize: "0.9rem" }}>
                Agent 3 — Risk & compliance
              </h4>
              <pre style={detailPre}>
                {details.risk ??
                  "Not run yet. Produces a deterministic risk decision, policy evidence, and required approvers."}
              </pre>
            </section>
            <section>
              <h4 style={{ margin: "0 0 0.35rem", fontSize: "0.9rem" }}>
                Agent 4 — Controlled execution
              </h4>
              <pre style={detailPre}>
                {details.execution ??
                  "Not run yet. Executes real tools after approval — Gemini chooses tools, writes emails, and sends them."}
              </pre>
            </section>

            {(artifacts.documents.length ||
              artifacts.calendar.length ||
              artifacts.tasks.length ||
              artifacts.notifications.length ||
              artifacts.emails.length) > 0 ? (
              <section className="artifact-panels" aria-label="Execution artifacts">
                {artifacts.documents.length > 0 ? (
                  <div>
                    <h4 style={{ margin: "0 0 0.35rem", fontSize: "0.9rem" }}>
                      Generated documents ({artifacts.documents.length})
                    </h4>
                    <ul className="artifact-list">
                      {artifacts.documents.map((doc: any) => (
                        <li key={doc.id || doc.title}>
                          <button
                            type="button"
                            className="linkish"
                            onClick={() =>
                              setOpenDocId((id) => (id === doc.id ? null : doc.id))
                            }
                          >
                            {doc.title || "Document"}
                          </button>
                          <span className="muted">
                            {" "}
                            · {doc.doc_type_label || doc.doc_type || "memo"}
                            {doc.word_count != null ? ` · ${doc.word_count} words` : ""}
                          </span>
                          {doc.summary ? (
                            <p className="muted tight">{doc.summary}</p>
                          ) : doc.content_preview ? (
                            <p className="muted tight">{doc.content_preview}</p>
                          ) : null}
                          {openDocId === doc.id ? (
                            <pre className="doc-body compact">
                              {doc.content || doc.content_preview}
                            </pre>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {artifacts.calendar.length > 0 ? (
                  <div>
                    <h4 style={{ margin: "0 0 0.35rem", fontSize: "0.9rem" }}>
                      Calendar ({artifacts.calendar.length})
                    </h4>
                    <ul className="artifact-list">
                      {artifacts.calendar.map((ev: any) => (
                        <li key={ev.id || ev.title}>
                          <strong>{ev.title || "Meeting"}</strong>
                          <span className="muted">
                            {" "}
                            · {ev.start_at || "—"} · {(ev.attendees || []).join(", ") || "no attendees"}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {artifacts.tasks.length > 0 ? (
                  <div>
                    <h4 style={{ margin: "0 0 0.35rem", fontSize: "0.9rem" }}>
                      Tasks ({artifacts.tasks.length})
                    </h4>
                    <ul className="artifact-list">
                      {artifacts.tasks.map((task: any) => (
                        <li key={task.id || task.title}>
                          <strong>{task.title || "Task"}</strong>
                          <span className="muted">
                            {" "}
                            → {task.assignee_name || (task.to || [])[0] || task.assignee_id || "—"}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {artifacts.notifications.length > 0 ? (
                  <div>
                    <h4 style={{ margin: "0 0 0.35rem", fontSize: "0.9rem" }}>
                      Notifications ({artifacts.notifications.length})
                    </h4>
                    <ul className="artifact-list">
                      {artifacts.notifications.map((n: any) => (
                        <li key={n.id || n.title}>
                          <strong>{n.title || "Process notification"}</strong>
                          <p className="muted tight">
                            {n.summary ||
                              `To ${(n.to || []).join(", ") || n.display_name || "internal"}`}
                          </p>
                          {(n.body_preview || n.body) && (
                            <p className="muted tight">
                              {String(n.body_preview || n.body).slice(0, 220)}
                              {String(n.body_preview || n.body).length > 220 ? "…" : ""}
                            </p>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {artifacts.emails.length > 0 ? (
                  <div>
                    <h4 style={{ margin: "0 0 0.35rem", fontSize: "0.9rem" }}>
                      Email outbox ({artifacts.emails.length})
                    </h4>
                    <ul className="artifact-list">
                      {artifacts.emails.map((e: any, idx: number) => (
                        <li key={e.id || idx}>
                          <strong>{e.subject || "(no subject)"}</strong>
                          <p className="muted tight">
                            {e.summary ||
                              `[${e.status || "sent"}] To ${(e.to || []).join?.(", ") || e.to || "?"}`}
                          </p>
                          {(e.body_preview || e.body) && (
                            <p className="muted tight">
                              {String(e.body_preview || e.body).slice(0, 220)}
                              {String(e.body_preview || e.body).length > 220 ? "…" : ""}
                            </p>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                <p className="muted tight">
                  Full org view: <Link to="/workspace">Workspace</Link>
                </p>
              </section>
            ) : null}
          </div>
        ) : null}
      </div>

      {notice ? (
        <p role="status" style={{ marginTop: "0.75rem", fontSize: "0.85rem", color: "#7a2e0b" }}>
          {notice}
        </p>
      ) : null}

      <div
        className="card-actions"
        style={{
          marginTop: "1.25rem",
          paddingTop: "1rem",
          borderTop: "1px solid var(--line, #e5e5e5)",
          display: "flex",
          gap: "0.5rem",
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <button
          type="button"
          disabled={disabled}
          onClick={() =>
            void runAction(
              "allocate",
              () => apiClient.allocateResources(process.id),
              "Agent 2 completed — see allocation details above.",
            )
          }
          style={primaryBtn}
        >
          {busy === "allocate" ? "Allocating…" : "Run Agent 2 (Allocation)"}
        </button>

        <button
          type="button"
          disabled={disabled}
          onClick={() =>
            void runAction(
              "risk",
              () => apiClient.analyzeRisk(process.id),
              "Agent 3 completed — see risk details above.",
            )
          }
          style={deepBtn}
        >
          {busy === "risk" ? "Analyzing…" : "Run Agent 3 (Risk Analysis)"}
        </button>

        <button
          type="button"
          disabled={disabled}
          onClick={() =>
            void runAction(
              "approval",
              () => apiClient.createApprovalPackage(process.id),
              "Approval package submitted — open Approvals to decide.",
            )
          }
          style={amberBtn}
        >
          {busy === "approval" ? "Submitting…" : "Submit for Approval"}
        </button>

        <button
          type="button"
          disabled={disabled}
          onClick={() =>
            void runAction(
              "execute",
              () =>
                apiClient.startExecution(process.id, {
                  dry_run: false,
                  auto_run: true,
                  max_steps: 20,
                }),
              "Agent 4 executed plan steps — see tools & emails above.",
            )
          }
          style={ghostBtn}
        >
          {busy === "execute" ? "Executing…" : "Run Agent 4 (Execute Plan)"}
        </button>
      </div>
    </article>
  );
}

const detailPre: CSSProperties = {
  margin: 0,
  whiteSpace: "pre-wrap",
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  fontSize: "0.78rem",
  lineHeight: 1.45,
  color: "var(--ink, #182218)",
};

const primaryBtn: CSSProperties = {
  background: "var(--brand, #1f6f4a)",
  color: "#fff",
  border: "none",
  borderRadius: "4px",
  padding: "0.4rem 0.8rem",
  fontSize: "0.8rem",
  fontWeight: 600,
  cursor: "pointer",
};

const deepBtn: CSSProperties = {
  ...primaryBtn,
  background: "var(--brand-deep, #12462f)",
};

const amberBtn: CSSProperties = {
  ...primaryBtn,
  background: "#8a5a12",
};

const ghostBtn: CSSProperties = {
  background: "transparent",
  color: "var(--ink, #182218)",
  border: "1px solid var(--line, #ccc)",
  borderRadius: "4px",
  padding: "0.4rem 0.8rem",
  fontSize: "0.8rem",
  fontWeight: 600,
  cursor: "pointer",
};
