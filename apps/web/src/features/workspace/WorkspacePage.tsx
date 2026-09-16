import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { EmptyState } from "../../components/ui/EmptyState";
import { LoadingState } from "../../components/ui/LoadingState";
import { RetryState } from "../../components/ui/RetryState";
import { RequirePermission } from "../../components/RouteGuards";
import { apiClient } from "../../lib/apiClient";
import { PERMISSIONS } from "../../lib/permissions";
import { useOrganization } from "../../providers/OrganizationProvider";

type TabKey = "emails" | "documents" | "notifications" | "calendar" | "tasks";

function formatWhen(value?: string | null) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function MetaRow({ label, value }: { label: string; value?: string | null }) {
  if (!value) return null;
  return (
    <p className="meta-row">
      <span className="meta-label">{label}</span>
      <span>{value}</span>
    </p>
  );
}

export function WorkspacePage() {
  const { activeOrganization } = useOrganization();
  const [tab, setTab] = useState<TabKey>("emails");
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [expandedEmailId, setExpandedEmailId] = useState<string | null>(null);
  const [expandedNotifId, setExpandedNotifId] = useState<string | null>(null);

  const emailsQuery = useQuery({
    queryKey: ["emails", activeOrganization?.id],
    queryFn: () => apiClient.listEmails(),
    enabled: Boolean(activeOrganization?.id),
  });
  const docsQuery = useQuery({
    queryKey: ["generated-documents", activeOrganization?.id],
    queryFn: () => apiClient.listGeneratedDocuments(),
    enabled: Boolean(activeOrganization?.id),
  });
  const calendarQuery = useQuery({
    queryKey: ["calendar-events", activeOrganization?.id],
    queryFn: () => apiClient.listCalendarEvents(),
    enabled: Boolean(activeOrganization?.id),
  });
  const tasksQuery = useQuery({
    queryKey: ["tasks", activeOrganization?.id],
    queryFn: () => apiClient.listTasks(),
    enabled: Boolean(activeOrganization?.id),
  });
  const notificationsQuery = useQuery({
    queryKey: ["workspace-notifications", activeOrganization?.id],
    queryFn: () => apiClient.listNotifications(),
    enabled: Boolean(activeOrganization?.id),
  });
  const selectedDocQuery = useQuery({
    queryKey: ["generated-document", selectedDocId],
    queryFn: () => apiClient.getGeneratedDocument(selectedDocId!),
    enabled: Boolean(selectedDocId),
  });

  const counts = useMemo(
    () => ({
      emails: emailsQuery.data?.length ?? 0,
      documents: docsQuery.data?.length ?? 0,
      notifications: notificationsQuery.data?.length ?? 0,
      calendar: calendarQuery.data?.length ?? 0,
      tasks: tasksQuery.data?.length ?? 0,
    }),
    [
      emailsQuery.data,
      docsQuery.data,
      notificationsQuery.data,
      calendarQuery.data,
      tasksQuery.data,
    ],
  );

  const activeQuery =
    tab === "emails"
      ? emailsQuery
      : tab === "documents"
        ? docsQuery
        : tab === "notifications"
          ? notificationsQuery
          : tab === "calendar"
            ? calendarQuery
            : tasksQuery;

  return (
    <RequirePermission
      permission={PERMISSIONS.PROCESSES_READ}
      fallback={
        <EmptyState
          title="Access restricted"
          description="Workspace artifacts require process read permission."
        />
      }
    >
      <section className="workspace-page">
        <p className="eyebrow">Artifacts</p>
        <h1>Workspace</h1>
        <p className="lede">
          Readable records of what Agent 4 produced — outbound emails, generated documents,
          notifications, meetings, and tasks.
        </p>

        <div className="workspace-tabs" role="tablist" aria-label="Workspace sections">
          {(
            [
              ["emails", "Emails"],
              ["documents", "Documents"],
              ["notifications", "Notifications"],
              ["calendar", "Calendar"],
              ["tasks", "Tasks"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              className={tab === key ? "is-active" : undefined}
              onClick={() => setTab(key)}
            >
              {label}
              <span className="tab-count">{counts[key]}</span>
            </button>
          ))}
        </div>

        {activeQuery.isLoading ? <LoadingState label="Loading workspace…" /> : null}
        {activeQuery.isError ? (
          <RetryState
            title="Could not load workspace"
            message="Retry to fetch Agent 4 artifacts."
            onRetry={() => void activeQuery.refetch()}
          />
        ) : null}

        {tab === "emails" && emailsQuery.data ? (
          emailsQuery.data.length === 0 ? (
            <EmptyState
              title="No emails yet"
              description="email.send, RFQs, calendar invites, and task notices appear here with full subject and body."
            />
          ) : (
            <ul className="workspace-cards">
              {emailsQuery.data.map((email) => {
                const open = expandedEmailId === email.id;
                return (
                  <li key={email.id} className="workspace-card">
                    <div className="workspace-card-head">
                      <div>
                        <p className="eyebrow">
                          {(email.status || "sent").toUpperCase()}
                          {email.mock === false ? " · LIVE" : ""}
                        </p>
                        <h2>{email.subject}</h2>
                        <p className="card-summary">
                          {email.summary ||
                            `Email to ${(email.to || []).join(", ") || "unknown recipient"}`}
                        </p>
                      </div>
                      <button
                        type="button"
                        className="ghost-btn"
                        onClick={() => setExpandedEmailId(open ? null : email.id)}
                      >
                        {open ? "Hide body" : "Read body"}
                      </button>
                    </div>
                    <MetaRow label="To" value={(email.to || []).join(", ") || "—"} />
                    <MetaRow label="Process" value={email.process_name || undefined} />
                    <MetaRow label="Provider" value={email.provider || undefined} />
                    <MetaRow label="Sent" value={formatWhen(email.created_at)} />
                    {!open && email.body_preview ? (
                      <p className="preview-block">{email.body_preview}</p>
                    ) : null}
                    {open ? <pre className="doc-body">{email.body || "(empty body)"}</pre> : null}
                  </li>
                );
              })}
            </ul>
          )
        ) : null}

        {tab === "documents" && docsQuery.data ? (
          <div className="workspace-split">
            <div>
              {docsQuery.data.length === 0 ? (
                <EmptyState
                  title="No generated documents yet"
                  description="document.generate creates RFQ packs, memos, and PO summaries here."
                />
              ) : (
                <ul className="workspace-cards">
                  {docsQuery.data.map((doc) => (
                    <li key={doc.id} className="workspace-card">
                      <p className="eyebrow">
                        {(doc.doc_type_label || doc.doc_type || "Document").toUpperCase()}
                        {doc.mock === false ? " · LIVE" : ""}
                      </p>
                      <h2>
                        <button
                          type="button"
                          className="linkish"
                          onClick={() => setSelectedDocId(doc.id)}
                        >
                          {doc.title}
                        </button>
                      </h2>
                      <p className="card-summary">
                        {doc.summary ||
                          `${doc.doc_type_label || doc.doc_type}: ${doc.content_preview || "No preview"}`}
                      </p>
                      <MetaRow label="Process" value={doc.process_name || undefined} />
                      <MetaRow
                        label="Length"
                        value={`${doc.word_count ?? 0} words · ${doc.byte_size} bytes`}
                      />
                      <MetaRow label="Created" value={formatWhen(doc.created_at)} />
                      {doc.content_preview ? (
                        <p className="preview-block">{doc.content_preview}</p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <aside className="workspace-detail" aria-live="polite">
              {selectedDocId == null ? (
                <p className="muted">Select a document title to open the full text.</p>
              ) : selectedDocQuery.isLoading ? (
                <LoadingState label="Opening document…" />
              ) : selectedDocQuery.data ? (
                <>
                  <p className="eyebrow">
                    {(
                      selectedDocQuery.data.doc_type_label ||
                      selectedDocQuery.data.doc_type ||
                      "Document"
                    ).toUpperCase()}
                  </p>
                  <h2>{selectedDocQuery.data.title}</h2>
                  <p className="card-summary">
                    {selectedDocQuery.data.summary ||
                      selectedDocQuery.data.content_preview ||
                      "Generated document"}
                  </p>
                  <MetaRow
                    label="Process"
                    value={selectedDocQuery.data.process_name || undefined}
                  />
                  <MetaRow
                    label="Created"
                    value={formatWhen(selectedDocQuery.data.created_at)}
                  />
                  <pre className="doc-body">{selectedDocQuery.data.content}</pre>
                </>
              ) : (
                <p className="muted">Document unavailable.</p>
              )}
            </aside>
          </div>
        ) : null}

        {tab === "notifications" && notificationsQuery.data ? (
          notificationsQuery.data.length === 0 ? (
            <EmptyState
              title="No notifications"
              description="notification.send posts descriptive alerts here and emails recipients when possible."
            />
          ) : (
            <ul className="workspace-cards">
              {notificationsQuery.data.map((n) => {
                const open = expandedNotifId === n.id;
                return (
                  <li key={n.id} className="workspace-card">
                    <div className="workspace-card-head">
                      <div>
                        <p className="eyebrow">
                          {n.status.toUpperCase()}
                          {n.email_status ? ` · EMAIL ${n.email_status.toUpperCase()}` : ""}
                          {n.mock === false ? " · LIVE" : ""}
                        </p>
                        <h2>{n.title || "Process notification"}</h2>
                        <p className="card-summary">
                          {n.summary || n.body_preview || n.body || "Notification"}
                        </p>
                      </div>
                      <button
                        type="button"
                        className="ghost-btn"
                        onClick={() => setExpandedNotifId(open ? null : n.id)}
                      >
                        {open ? "Collapse" : "Full message"}
                      </button>
                    </div>
                    <MetaRow
                      label="Recipient"
                      value={(n.to || []).join(", ") || n.display_name || "internal"}
                    />
                    <MetaRow label="Process" value={n.process_name || undefined} />
                    <MetaRow label="Created" value={formatWhen(n.created_at)} />
                    {!open && n.body_preview ? (
                      <p className="preview-block">{n.body_preview}</p>
                    ) : null}
                    {open ? <pre className="doc-body">{n.body || "(empty)"}</pre> : null}
                  </li>
                );
              })}
            </ul>
          )
        ) : null}

        {tab === "calendar" && calendarQuery.data ? (
          calendarQuery.data.length === 0 ? (
            <EmptyState
              title="No calendar events"
              description="calendar.create_event writes meetings and invite emails here."
            />
          ) : (
            <ul className="workspace-cards">
              {calendarQuery.data.map((ev) => (
                <li key={ev.id} className="workspace-card">
                  <p className="eyebrow">
                    {(ev.status || "confirmed").toUpperCase()}
                    {ev.mock === false ? " · LIVE" : ""}
                  </p>
                  <h2>{ev.title}</h2>
                  <p className="card-summary">
                    {ev.summary ||
                      `Meeting with ${(ev.attendees || []).join(", ") || "no attendees"}`}
                  </p>
                  <MetaRow label="Starts" value={formatWhen(ev.start_at)} />
                  <MetaRow label="Ends" value={ev.end_at ? formatWhen(ev.end_at) : undefined} />
                  <MetaRow label="Attendees" value={(ev.attendees || []).join(", ") || "—"} />
                  <MetaRow
                    label="Invites sent"
                    value={String((ev.invites_sent || []).length)}
                  />
                  <MetaRow label="Process" value={ev.process_name || undefined} />
                  {ev.description_preview || ev.description ? (
                    <p className="preview-block">
                      {ev.description_preview || ev.description}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          )
        ) : null}

        {tab === "tasks" && tasksQuery.data ? (
          tasksQuery.data.length === 0 ? (
            <EmptyState
              title="No tasks assigned"
              description="task.assign creates follow-ups with assignee and email details."
            />
          ) : (
            <ul className="workspace-cards">
              {tasksQuery.data.map((task) => (
                <li key={task.id} className="workspace-card">
                  <p className="eyebrow">
                    {(task.status || "open").toUpperCase()}
                    {task.email_status ? ` · EMAIL ${task.email_status.toUpperCase()}` : ""}
                    {task.mock === false ? " · LIVE" : ""}
                  </p>
                  <h2>{task.title}</h2>
                  <p className="card-summary">
                    {task.summary ||
                      `Assigned to ${task.assignee_name || (task.to || [])[0] || "—"}`}
                  </p>
                  <MetaRow
                    label="Assignee"
                    value={
                      task.assignee_name ||
                      (task.to || []).join(", ") ||
                      task.assignee_id ||
                      "—"
                    }
                  />
                  <MetaRow label="Due" value={task.due_at ? formatWhen(task.due_at) : undefined} />
                  <MetaRow label="Process" value={task.process_name || undefined} />
                  <MetaRow label="Created" value={formatWhen(task.created_at)} />
                  {task.description_preview || task.description ? (
                    <p className="preview-block">
                      {task.description_preview || task.description}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          )
        ) : null}

        <p className="muted">
          Process-linked views also appear on <Link to="/plans">Plans</Link> and{" "}
          <Link to="/runs">Active runs</Link> after Agent 4 executes.
        </p>
      </section>
    </RequirePermission>
  );
}
