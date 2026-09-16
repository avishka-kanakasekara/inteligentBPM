import { EmptyState } from "../../components/ui/EmptyState";
import { PageHeader } from "../../components/ui/PageHeader";
import { RequireFeature, RequirePermission } from "../../components/RouteGuards";
import { PERMISSIONS } from "../../lib/permissions";

const INTEGRATIONS = [
  {
    name: "Email",
    description: "Outbound operational email for RFQs, notifications, and approvals.",
    status: "Connected · mock mode",
  },
  {
    name: "Suppliers",
    description: "Supplier directory and quote request connectors.",
    status: "Connected · mock mode",
  },
  {
    name: "Purchasing",
    description: "Purchase order drafts and procurement handoff.",
    status: "Draft only",
  },
];

export function IntegrationsPage() {
  return (
    <RequirePermission
      permission={PERMISSIONS.INTEGRATIONS_CONFIGURE}
      fallback={
        <EmptyState
          title="Access restricted"
          description="Only owners and admins can configure integrations."
        />
      }
    >
      <RequireFeature
        feature="integrations.basic"
        fallback={
          <EmptyState
            title="Upgrade required"
            description="Integrations are available on Enterprise and Pro Max plans."
          />
        }
      >
        <section>
          <PageHeader
            eyebrow="Administration"
            title="Integrations"
            description="Email, supplier, purchasing, and billing connectors. Credentials stay in the secret manager — never in the browser."
          />
          <div className="split-panels">
            {INTEGRATIONS.map((item) => (
              <article key={item.name} className="workspace-card">
                <div className="workspace-card-head">
                  <h2>{item.name}</h2>
                  <span className="status-pill tone-info">{item.status}</span>
                </div>
                <p className="card-summary">{item.description}</p>
                <button type="button" className="ghost-btn" disabled title="Configuration UI uses existing secure handlers">
                  Configure integration
                </button>
              </article>
            ))}
          </div>
        </section>
      </RequireFeature>
    </RequirePermission>
  );
}
