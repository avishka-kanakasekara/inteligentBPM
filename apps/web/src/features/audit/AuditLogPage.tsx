import { EmptyState } from "../../components/ui/EmptyState";
import { PageHeader } from "../../components/ui/PageHeader";
import { RequirePermission } from "../../components/RouteGuards";
import { PERMISSIONS } from "../../lib/permissions";

const EVENTS = [
  {
    action: "approval.decided",
    actor: "Alex Owner",
    detail: "Laptop procurement approved",
    result: "success",
  },
  {
    action: "document.created",
    actor: "Sam Employee",
    detail: "Uploaded RFQ notes",
    result: "success",
  },
];

export function AuditLogPage() {
  return (
    <RequirePermission
      permission={PERMISSIONS.AUDIT_READ}
      fallback={
        <EmptyState title="Access restricted" description="Audit log requires auditor access." />
      }
    >
      <section>
        <PageHeader
          eyebrow="Compliance"
          title="Audit log"
          description="Append-only decisions and side effects for this organization."
        />
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Action</th>
                <th scope="col">Actor</th>
                <th scope="col">Detail</th>
                <th scope="col">Result</th>
              </tr>
            </thead>
            <tbody>
              {EVENTS.map((event) => (
                <tr key={event.action + event.detail}>
                  <td>
                    <code style={{ fontFamily: "var(--font-mono)", fontSize: "0.8rem" }}>
                      {event.action}
                    </code>
                  </td>
                  <td>{event.actor}</td>
                  <td>{event.detail}</td>
                  <td>
                    <span className="status-pill tone-success">{event.result}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </RequirePermission>
  );
}
