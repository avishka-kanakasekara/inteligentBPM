import { useState, useEffect, useMemo, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { EmptyState } from "../../components/ui/EmptyState";
import { LoadingState } from "../../components/ui/LoadingState";
import { RetryState } from "../../components/ui/RetryState";
import { RequireFeature } from "../../components/RouteGuards";
import { ApiError, apiClient } from "../../lib/apiClient";
import { useOrganization } from "../../providers/OrganizationProvider";

const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md", ".markdown", ".eml", ".msg"];
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

type AttachedDocument = {
  id: string;
  name: string;
};

type ChatMessage = {
  id?: string;
  role: "user" | "assistant";
  content: string;
  document_ids?: string[];
  clarifying_questions?: string[];
  missing_information?: Array<{ field?: string; question: string }>;
  intent?: {
    goal?: string;
    actors?: string[];
    systems?: string[];
  };
};

function discoveryErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      const comma = result.indexOf(",");
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.onerror = () => reject(reader.error ?? new Error("Could not read file"));
    reader.readAsDataURL(file);
  });
}

type PlanStep = {
  step_id: string;
  action_type: string;
  description: string;
  required_resources?: string[];
  risk_level?: string;
  allowed_tools?: string[];
};

type DraftedPlan = {
  version_id: string;
  version_number: number;
  status: string;
  plan: {
    goal?: string;
    steps: PlanStep[];
    missing_information?: Array<{ question: string }>;
  };
};

export function DiscoveryChatPage() {
  const { activeOrganization } = useOrganization();
  const queryClient = useQueryClient();

  const [selectedProcessId, setSelectedProcessId] = useState<string>("");
  const [newProcessName, setNewProcessName] = useState("");
  const [newProcessDesc, setNewProcessDesc] = useState("");
  const [showNewModal, setShowNewModal] = useState(false);
  const [inputMessage, setInputMessage] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pendingDocs, setPendingDocs] = useState<AttachedDocument[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [draftedPlan, setDraftedPlan] = useState<DraftedPlan | null>(null);
  const [planConfirmed, setPlanConfirmed] = useState(false);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const chatLogRef = useRef<HTMLDivElement>(null);
  const messageInputRef = useRef<HTMLInputElement>(null);
  const processNameInputRef = useRef<HTMLInputElement>(null);

  // Load process summaries
  const processesQuery = useQuery({
    queryKey: ["processes", activeOrganization?.id],
    queryFn: () => apiClient.listProcesses(),
    enabled: Boolean(activeOrganization?.id),
  });

  const processes = processesQuery.data ?? [];

  const documentsQuery = useQuery({
    queryKey: ["documents", activeOrganization?.id],
    queryFn: () => apiClient.listDocuments(),
    enabled: Boolean(activeOrganization?.id),
  });

  const documentNames = useMemo(() => {
    const names = new Map<string, string>();
    for (const doc of documentsQuery.data?.items ?? []) {
      names.set(doc.id, doc.file_name || doc.title);
    }
    for (const doc of pendingDocs) names.set(doc.id, doc.name);
    return names;
  }, [documentsQuery.data, pendingDocs]);

  const sessionDocumentIds = useMemo(() => {
    const ids = new Set<string>();
    for (const message of messages) {
      for (const id of message.document_ids ?? []) ids.add(id);
    }
    return Array.from(ids);
  }, [messages]);

  // Auto-select first process if none selected
  useEffect(() => {
    if (!selectedProcessId && processes.length > 0) {
      setSelectedProcessId(processes[0].id);
    }
  }, [processes, selectedProcessId]);

  // Load chat history when selected process changes
  const chatHistoryQuery = useQuery({
    queryKey: ["discovery-chat", selectedProcessId],
    queryFn: async () => {
      if (!selectedProcessId) return null;
      return apiClient.getDiscoveryChat(selectedProcessId);
    },
    enabled: Boolean(selectedProcessId),
  });

  useEffect(() => {
    if (chatHistoryQuery.data?.messages?.length) {
      const mapped: ChatMessage[] = chatHistoryQuery.data.messages.map((m: any) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        document_ids: Array.isArray(m.document_ids) ? m.document_ids : [],
        clarifying_questions: m.clarifying_questions,
        intent: m.intent,
      }));
      setMessages(mapped);
    } else if (selectedProcessId && !chatHistoryQuery.isLoading) {
      setMessages([
        {
          role: "assistant",
          content:
            "I am Agent 1 (Process Discovery). Describe the business process you want to automate. I will ask what is missing and draft an execution plan. Vertex Gemini is used only when a Google Cloud project and model are configured.",
        },
      ]);
    }
  }, [chatHistoryQuery.data, selectedProcessId, chatHistoryQuery.isLoading]);

  // Create process mutation
  const createProcessMutation = useMutation({
    mutationFn: (data: { name: string; description?: string }) =>
      apiClient.createProcess(data),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: ["processes"] });
      setSelectedProcessId(created.id);
      setShowNewModal(false);
      setNewProcessName("");
      setNewProcessDesc("");
      setDraftedPlan(null);
      setPlanConfirmed(false);
      setPendingDocs([]);
      setCreateError(null);
      setActionError(null);
      setActionNotice(`Created process: "${created.name}"`);
    },
    onError: (err) => {
      setCreateError(discoveryErrorMessage(err, "Could not create the process."));
    },
  });

  // Chat message mutation
  const sendChatMutation = useMutation({
    mutationFn: ({
      procId,
      text,
      documentIds,
    }: {
      procId: string;
      text: string;
      documentIds: string[];
      attachments: AttachedDocument[];
      composerText: string;
    }) => apiClient.chatDiscovery(procId, text, documentIds),
    onSuccess: (reply) => {
      setActionError(null);
      setMessages((prev) => [
        ...prev,
        {
          id: reply.id,
          role: "assistant",
          content: reply.content,
          clarifying_questions: reply.clarifying_questions,
          missing_information: reply.missing_information,
          intent: reply.intent,
        },
      ]);
    },
    onError: (err, variables) => {
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last?.role === "user" && last.content === variables.text) next.pop();
        return next;
      });
      setInputMessage(variables.composerText);
      if (variables.attachments.length > 0) setPendingDocs(variables.attachments);
      setActionError(discoveryErrorMessage(err, "Could not send the discovery message."));
    },
  });

  // Draft plan mutation (Vertex Gemini)
  const draftPlanMutation = useMutation({
    mutationFn: ({ procId, documentIds }: { procId: string; documentIds: string[] }) =>
      apiClient.draftPlan(procId, { document_ids: documentIds }),
    onSuccess: (res) => {
      setDraftedPlan(res);
      setPlanConfirmed(res.status === "confirmed");
      setActionError(null);
      setActionNotice(
        `Agent 1 drafted plan v${res.version_number} with ${res.plan?.steps?.length || 0} steps.`,
      );
    },
    onError: (err) => {
      setActionError(discoveryErrorMessage(err, "Could not draft a plan."));
    },
  });

  // Confirm plan mutation
  const confirmPlanMutation = useMutation({
    mutationFn: ({ procId, versionId }: { procId: string; versionId: string }) =>
      apiClient.confirmPlan(procId, versionId),
    onSuccess: () => {
      setActionError(null);
      setPlanConfirmed(true);
      setActionNotice("Plan confirmed! Ready for Agent 2 (Allocation) and Agent 3 (Risk).");
      void queryClient.invalidateQueries({ queryKey: ["processes"] });
    },
    onError: (err) => {
      setActionError(discoveryErrorMessage(err, "Could not confirm this plan."));
    },
  });

  async function handleFilesSelected(fileList: FileList | null) {
    if (!fileList || !selectedProcessId) return;
    setUploadError(null);
    const files = Array.from(fileList);
    setUploading(true);
    try {
      for (const file of files) {
        const ext = file.name.includes(".")
          ? file.name.slice(file.name.lastIndexOf(".")).toLowerCase()
          : "";
        if (!ACCEPTED_EXTENSIONS.includes(ext)) {
          throw new Error(`${file.name} is not a supported type (${ACCEPTED_EXTENSIONS.join(", ")})`);
        }
        if (file.size > MAX_UPLOAD_BYTES) {
          throw new Error(`${file.name} is larger than 25 MB`);
        }
        const content_base64 = await fileToBase64(file);
        const created = await apiClient.ingestDocument({
          title: file.name,
          file_name: file.name,
          content_base64,
          mime_type: file.type || undefined,
          document_type: "discovery",
        });
        const attached = { id: created.id, name: created.file_name || created.title || file.name };
        setPendingDocs((prev) => (prev.some((doc) => doc.id === attached.id) ? prev : [...prev, attached]));
      }
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Upload failed";
      setUploadError(message);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    }
  }

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedProcessId || sendChatMutation.isPending || uploading) return;
    const userText = inputMessage.trim();
    if (!userText && pendingDocs.length === 0) return;

    const attachments = pendingDocs;
    const documentIds = attachments.map((doc) => doc.id);
    const content =
      userText ||
      `Please use these attached documents as source material: ${attachments.map((doc) => doc.name).join(", ")}`;
    setInputMessage("");
    setPendingDocs([]);
    setMessages((prev) => [...prev, { role: "user", content, document_ids: documentIds }]);
    sendChatMutation.mutate({ procId: selectedProcessId, text: content, documentIds, attachments, composerText: userText });
  };

  useEffect(() => {
    const log = chatLogRef.current;
    if (!log) return;
    log.scrollTop = log.scrollHeight;
  }, [messages, sendChatMutation.isPending]);

  useEffect(() => {
    if (!showNewModal) return;
    processNameInputRef.current?.focus();
  }, [showNewModal]);

  useEffect(() => {
    if (!showNewModal) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || createProcessMutation.isPending) return;
      setShowNewModal(false);
      setNameError(null);
      setCreateError(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [showNewModal, createProcessMutation.isPending]);

  const handleApplyQuestion = (question: string) => {
    setInputMessage(question);
    messageInputRef.current?.focus();
  };

  return (
    <RequireFeature
      feature="process.discovery"
      fallback={
        <EmptyState
          title="Discovery not entitled"
          description="Your subscription plan does not include intelligent process discovery."
        />
      }
    >
      <section className="discovery-page">
        <div className="discovery-header">
          <div>
            <p className="eyebrow">Discovery</p>
            <h1>Process discovery</h1>
            <p className="lede">
              Interview-driven discovery, dependency extraction, and formal execution plan generation.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              setCreateError(null);
              setNameError(null);
              setShowNewModal(true);
            }}
          >
            Create process
          </button>
        </div>

        <div className="discovery-toolbar">
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flex: 1, flexWrap: "wrap" }}>
            <label htmlFor="process-selector">Active process</label>
            {processesQuery.isLoading ? (
              <LoadingState label="Loading processes…" />
            ) : processesQuery.isError ? (
              <RetryState
                title="Could not load processes"
                message={discoveryErrorMessage(
                  processesQuery.error,
                  "The process list could not be loaded.",
                )}
                onRetry={() => {
                  void processesQuery.refetch();
                }}
              />
            ) : processes.length === 0 ? (
              <span className="muted">No processes yet. Create one to begin.</span>
            ) : (
              <select
                id="process-selector"
                value={selectedProcessId}
                onChange={(e) => {
                  setSelectedProcessId(e.target.value);
                  setDraftedPlan(null);
                  setPlanConfirmed(false);
                  setPendingDocs([]);
                  setUploadError(null);
                  setActionError(null);
                  setActionNotice(null);
                }}
                style={{ flex: 1, maxWidth: "400px" }}
              >
                {processes.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.status})
                  </option>
                ))}
              </select>
            )}
          </div>

          {selectedProcessId ? (
            <button
              type="button"
              className="btn-secondary"
              onClick={() =>
                draftPlanMutation.mutate({
                  procId: selectedProcessId,
                  documentIds: Array.from(new Set([...sessionDocumentIds, ...pendingDocs.map((d) => d.id)])),
                })
              }
              disabled={draftPlanMutation.isPending || sendChatMutation.isPending}
            >
              {draftPlanMutation.isPending ? "Drafting plan…" : "Draft plan"}
            </button>
          ) : null}
        </div>

        {actionNotice ? (
          <div className="notice-banner" role="status" aria-live="polite">
            <span>{actionNotice}</span>
            <button type="button" className="ghost-btn" onClick={() => setActionNotice(null)}>
              Dismiss
            </button>
          </div>
        ) : null}

        {actionError ? (
          <div className="chat-upload-error discovery-action-error" role="alert">
            <span>{actionError}</span>
            <button type="button" className="ghost-btn" onClick={() => setActionError(null)}>
              Dismiss
            </button>
          </div>
        ) : null}

        {showNewModal ? (
          <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="new-process-title">
            <div className="modal-card">
              <h2 id="new-process-title">Create process</h2>
              <p className="muted" style={{ marginBottom: "1.25rem" }}>
                Name the workflow you want to discover and automate.
              </p>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!newProcessName.trim()) {
                    setNameError("Enter a process name.");
                    return;
                  }
                  setNameError(null);
                  createProcessMutation.mutate({
                    name: newProcessName.trim(),
                    description: newProcessDesc.trim() || undefined,
                  });
                }}
              >
                <div style={{ marginBottom: "1rem" }}>
                  <label htmlFor="new-proc-name" style={{ display: "block", marginBottom: "0.35rem" }}>
                    Process Name *
                  </label>
                  <input
                    ref={processNameInputRef}
                    id="new-proc-name"
                    type="text"
                    required
                    placeholder="e.g. Vendor Onboarding & Purchasing Approval"
                    value={newProcessName}
                    onChange={(e) => {
                      setNewProcessName(e.target.value);
                      if (nameError) setNameError(null);
                    }}
                    aria-invalid={Boolean(nameError)}
                    aria-describedby={nameError ? "new-proc-name-error" : undefined}
                    style={{ width: "100%" }}
                  />
                  {nameError ? (
                    <p id="new-proc-name-error" className="chat-upload-error" role="alert">
                      {nameError}
                    </p>
                  ) : null}
                </div>
                <div style={{ marginBottom: "1.25rem" }}>
                  <label htmlFor="new-proc-desc" style={{ display: "block", marginBottom: "0.35rem" }}>
                    Initial Description (Optional)
                  </label>
                  <textarea
                    id="new-proc-desc"
                    rows={3}
                    placeholder="Briefly describe the business goals, expected systems, and approvers."
                    value={newProcessDesc}
                    onChange={(e) => setNewProcessDesc(e.target.value)}
                    style={{ width: "100%" }}
                  />
                </div>
                {createError ? (
                  <p className="chat-upload-error" role="alert" style={{ marginBottom: "0.75rem" }}>
                    {createError}
                  </p>
                ) : null}
                <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem" }}>
                  <button
                    type="button"
                    className="ghost-btn"
                    onClick={() => {
                      setShowNewModal(false);
                      setNameError(null);
                      setCreateError(null);
                    }}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={createProcessMutation.isPending || !newProcessName.trim()}
                  >
                    {createProcessMutation.isPending ? "Creating…" : "Create process"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        ) : null}

        <div className={draftedPlan ? "discovery-grid" : "discovery-grid solo"}>
          <div className="chat-panel">
            <div
              className="chat-log"
              ref={chatLogRef}
              role="log"
              aria-label="Discovery conversation"
              aria-busy={sendChatMutation.isPending}
            >
              {chatHistoryQuery.isLoading ? (
                <LoadingState label="Loading conversation…" />
              ) : chatHistoryQuery.isError ? (
                <RetryState
                  title="Could not load the conversation"
                  message={discoveryErrorMessage(
                    chatHistoryQuery.error,
                    "Discovery history could not be loaded.",
                  )}
                  onRetry={() => {
                    void chatHistoryQuery.refetch();
                  }}
                />
              ) : !selectedProcessId ? (
                <EmptyState
                  title="No process selected"
                  description="Create a process to start discovery."
                />
              ) : (
                messages.map((m, idx) => (
                  <div
                    key={m.id ?? `${m.role}-${idx}`}
                    className={`chat-bubble ${m.role === "assistant" ? "assistant" : "user"}`}
                  >
                    <div style={{ fontSize: "0.75rem", opacity: 0.8, marginBottom: "0.25rem", fontWeight: 600 }}>
                      {m.role === "user" ? "You" : "Discovery assistant"}
                    </div>
                    <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.45 }}>{m.content}</div>
                    {m.document_ids && m.document_ids.length > 0 ? (
                      <div className="chat-attachments">
                        {m.document_ids.map((id) => (
                          <span key={id} className="chat-chip">
                            <span>{documentNames.get(id) || "Attached document"}</span>
                          </span>
                        ))}
                      </div>
                    ) : null}

                    {/* Clarifying questions suggestions */}
                    {m.clarifying_questions && m.clarifying_questions.length > 0 && (
                      <div
                        style={{
                          marginTop: "0.75rem",
                          paddingTop: "0.5rem",
                          borderTop: "1px dashed var(--border)",
                        }}
                      >
                        <strong style={{ fontSize: "0.8rem", color: "var(--accent-hover)" }}>
                          Clarifying Questions:
                        </strong>
                        <ul style={{ margin: "0.4rem 0 0", paddingLeft: "1.2rem", fontSize: "0.85rem", color: "var(--text-secondary)" }}>
                          {m.clarifying_questions.map((q, qIdx) => (
                            <li key={qIdx} style={{ marginBottom: "0.35rem" }}>
                              <span>{q}</span>{" "}
                              <button
                                type="button"
                                className="linkish"
                                onClick={() => handleApplyQuestion(q)}
                                style={{ marginLeft: "0.3rem" }}
                              >
                                Answer this
                              </button>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ))
              )}

              {sendChatMutation.isPending ? (
                <div className="chat-bubble assistant" role="status" aria-live="polite">
                  Analyzing your response…
                </div>
              ) : null}
            </div>

            <form className="chat-composer" onSubmit={handleSendMessage}>
              <div className="chat-upload">
                <input
                  ref={fileInputRef}
                  id="discovery-document-upload"
                  type="file"
                  multiple
                  accept={ACCEPTED_EXTENSIONS.join(",")}
                  disabled={!selectedProcessId || uploading || sendChatMutation.isPending}
                  aria-describedby={uploadError ? "discovery-upload-error" : undefined}
                  onChange={(e) => void handleFilesSelected(e.target.files)}
                />
                <label htmlFor="discovery-document-upload">
                  <strong>Upload documents</strong>
                  <p>PDF, Word, Excel, CSV, text, Markdown, or email. Up to 25 MB each.</p>
                </label>
              </div>
              {pendingDocs.length > 0 ? (
                <div className="chat-attachments" aria-label="Documents to send">
                  {pendingDocs.map((doc) => (
                    <span key={doc.id} className="chat-chip">
                      <span>{doc.name}</span>
                      <button
                        type="button"
                        aria-label={`Remove ${doc.name}`}
                        onClick={() =>
                          setPendingDocs((prev) => prev.filter((item) => item.id !== doc.id))
                        }
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              ) : null}
              {uploading ? (
                <p className="chat-upload-status" role="status">
                  Uploading documents…
                </p>
              ) : null}
              {uploadError ? (
                <p id="discovery-upload-error" className="chat-upload-error" role="alert">
                  {uploadError}
                </p>
              ) : null}
              <div className="chat-composer-row">
                <input
                  type="text"
                  placeholder={
                    selectedProcessId
                      ? "Describe the process, or send the uploaded documents…"
                      : "Select or create a process first…"
                  }
                  disabled={!selectedProcessId || sendChatMutation.isPending || uploading}
                  ref={messageInputRef}
                  value={inputMessage}
                  onChange={(e) => setInputMessage(e.target.value)}
                  aria-label="Discovery message"
                />
                <button
                  type="submit"
                  disabled={
                    !selectedProcessId ||
                    uploading ||
                    sendChatMutation.isPending ||
                    (!inputMessage.trim() && pendingDocs.length === 0)
                  }
                >
                  {sendChatMutation.isPending ? "Sending…" : "Send"}
                </button>
              </div>
            </form>
          </div>

          {draftedPlan ? (
            <div className="plan-panel">
              <div className="org-top" style={{ marginBottom: "1rem", paddingBottom: "0.75rem", borderBottom: "1px solid var(--color-border-subtle)" }}>
                <div>
                  <h3>Draft plan (v{draftedPlan.version_number})</h3>
                  <span className={`status-pill ${planConfirmed ? "tone-success" : "tone-warning"}`}>
                    {planConfirmed ? "Confirmed" : "Draft"}
                  </span>
                </div>

                {!planConfirmed ? (
                  <button
                    type="button"
                    onClick={() =>
                      confirmPlanMutation.mutate({
                        procId: selectedProcessId,
                        versionId: draftedPlan.version_id,
                      })
                    }
                    disabled={confirmPlanMutation.isPending}
                  >
                    {confirmPlanMutation.isPending ? "Confirming…" : "Confirm and create plan"}
                  </button>
                ) : null}
              </div>

              {draftedPlan.plan?.goal && (
                <div style={{ marginBottom: "1rem", fontSize: "0.9rem", fontStyle: "italic", color: "var(--text-secondary)" }}>
                  <strong>Goal:</strong> {draftedPlan.plan.goal}
                </div>
              )}

              <h4 style={{ margin: "0 0 0.5rem", fontSize: "0.95rem" }}>
                Execution Steps ({draftedPlan.plan?.steps?.length || 0})
              </h4>
              <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
                {(draftedPlan.plan?.steps || []).length === 0 ? (
                  <p className="muted">This draft has no execution steps yet.</p>
                ) : null}
                {(draftedPlan.plan?.steps || []).map((step, idx) => (
                  <div
                    key={step.step_id || idx}
                    style={{
                      padding: "0.75rem",
                      border: "1px solid var(--border)",
                      borderRadius: "var(--radius-lg)",
                      background: "var(--bg-elevated)",
                      fontSize: "0.875rem",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.25rem" }}>
                      <strong>
                        {idx + 1}. {step.step_id}
                      </strong>
                      <span
                        style={{
                          background: "var(--bg-surface)",
                          border: "1px solid var(--border)",
                          padding: "0.15rem 0.5rem",
                          borderRadius: "4px",
                          fontSize: "0.75rem",
                          fontWeight: 600,
                        }}
                      >
                        {step.action_type}
                      </span>
                    </div>
                    <p style={{ margin: "0.25rem 0", lineHeight: 1.4, color: "var(--text-secondary)" }}>{step.description}</p>
                    <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "0.4rem", fontSize: "0.75rem" }}>
                      {step.risk_level && (
                        <span
                          style={{
                            color: step.risk_level === "high" || step.risk_level === "critical" ? "var(--danger)" : "var(--success)",
                            fontWeight: 600,
                          }}
                        >
                          Risk: {step.risk_level}
                        </span>
                      )}
                      {step.required_resources && step.required_resources.length > 0 && (
                        <span className="muted">
                          Resources: {step.required_resources.join(", ")}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </section>
    </RequireFeature>
  );
}
