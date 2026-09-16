import { PageHeader } from "../../components/ui/PageHeader";
import { useOrganization } from "../../providers/OrganizationProvider";
import { useAuth } from "../../providers/AuthProvider";

export function SettingsPage() {
  const { user } = useAuth();
  const { activeOrganization } = useOrganization();

  return (
    <section>
      <PageHeader
        eyebrow="Administration"
        title="Settings"
        description="Workspace preferences for the current session."
      />
      <div className="settings-layout">
        <nav className="settings-nav" aria-label="Settings sections">
          <button type="button" className="is-active">
            Profile
          </button>
          <button type="button" disabled title="Coming soon">
            Organization
          </button>
          <button type="button" disabled title="Coming soon">
            Notifications
          </button>
          <button type="button" disabled title="Coming soon">
            Security
          </button>
        </nav>
        <div className="ops-panel">
          <h2>Profile</h2>
          <dl className="status-grid" style={{ marginTop: "1rem" }}>
            <div>
              <dt>Signed-in user</dt>
              <dd>{user?.email}</dd>
            </div>
            <div>
              <dt>Display name</dt>
              <dd>{user?.displayName || "—"}</dd>
            </div>
            <div>
              <dt>Active organization</dt>
              <dd>{activeOrganization?.name}</dd>
            </div>
            <div>
              <dt>Membership role</dt>
              <dd>{activeOrganization?.membership_role ?? "—"}</dd>
            </div>
            <div>
              <dt>API mode</dt>
              <dd>{(import.meta.env.VITE_USE_MOCK_API ?? "true") === "false" ? "live" : "mock"}</dd>
            </div>
          </dl>
        </div>
      </div>
    </section>
  );
}
