import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "../../components/ui/PageHeader";
import { useOrganization } from "../../providers/OrganizationProvider";
import { useAuth } from "../../providers/AuthProvider";

type SettingsTab = "profile" | "organization" | "notifications" | "security";

const TABS: { id: SettingsTab; label: string }[] = [
  { id: "profile", label: "Profile" },
  { id: "organization", label: "Organization" },
  { id: "notifications", label: "Notifications" },
  { id: "security", label: "Security" },
];

function initials(name?: string | null, email?: string | null) {
  const source = (name || email || "?").trim();
  const parts = source.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  return source.slice(0, 2).toUpperCase();
}

function planLabel(code?: string | null) {
  if (!code) return "—";
  return code
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function SettingsPage() {
  const { user, signOut } = useAuth();
  const { activeOrganization, organizations } = useOrganization();
  const [tab, setTab] = useState<SettingsTab>("profile");
  const [prefs, setPrefs] = useState({
    processUpdates: true,
    approvalRequests: true,
    weeklyDigest: false,
  });
  const [savedFlash, setSavedFlash] = useState<string | null>(null);

  const apiMode =
    (import.meta.env.VITE_USE_MOCK_API ?? "true") === "false" ? "live" : "mock";
  const authProvider = import.meta.env.VITE_SUPABASE_URL
    ? "Supabase Auth"
    : "Local / mock session";

  const avatar = useMemo(
    () => initials(user?.displayName, user?.email),
    [user?.displayName, user?.email],
  );

  function flash(message: string) {
    setSavedFlash(message);
    window.setTimeout(() => setSavedFlash(null), 2200);
  }

  return (
    <section className="settings-page">
      <PageHeader
        eyebrow="Administration"
        title="Settings"
        description="Manage your profile, workspace context, and session preferences."
      />

      <div className="settings-identity">
        <div className="settings-avatar" aria-hidden="true">
          {avatar}
        </div>
        <div className="settings-identity-copy">
          <h2>{user?.displayName || user?.email || "Signed-in user"}</h2>
          <p>
            {user?.email}
            {activeOrganization ? ` · ${activeOrganization.name}` : ""}
          </p>
          <div className="badge-row">
            {activeOrganization?.membership_role ? (
              <span className="status-pill tone-info">
                {activeOrganization.membership_role}
              </span>
            ) : null}
            <span className={`status-pill ${apiMode === "live" ? "tone-success" : "tone-info"}`}>
              API {apiMode}
            </span>
            {activeOrganization?.plan_code ? (
              <span className="status-pill">{planLabel(activeOrganization.plan_code)}</span>
            ) : null}
          </div>
        </div>
        <div className="settings-identity-actions">
          <Link to="/organizations" className="btn ghost-btn">
            Switch organization
          </Link>
          <button type="button" className="ghost-btn" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </div>

      <div className="settings-shell">
        <div className="settings-tabs" role="tablist" aria-label="Settings sections">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={tab === item.id}
              className={tab === item.id ? "is-active" : undefined}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>

        {savedFlash ? (
          <p className="settings-flash" role="status">
            {savedFlash}
          </p>
        ) : null}

        <div className="settings-body" role="tabpanel">
          {tab === "profile" ? (
            <div className="settings-section">
              <header className="settings-section-head">
                <div>
                  <h3>Profile</h3>
                  <p>Account details from the authenticated session.</p>
                </div>
              </header>
              <div className="settings-field-list">
                <div className="settings-field">
                  <div>
                    <span className="settings-field-label">Display name</span>
                    <span className="settings-field-hint">Shown across approvals and audit events</span>
                  </div>
                  <div className="settings-field-value">{user?.displayName || "—"}</div>
                </div>
                <div className="settings-field">
                  <div>
                    <span className="settings-field-label">Email</span>
                    <span className="settings-field-hint">Sign-in identity</span>
                  </div>
                  <div className="settings-field-value">{user?.email || "—"}</div>
                </div>
                <div className="settings-field">
                  <div>
                    <span className="settings-field-label">User ID</span>
                    <span className="settings-field-hint">Internal identifier</span>
                  </div>
                  <div className="settings-field-value">
                    <code className="mono-chip">{user?.id ?? "—"}</code>
                  </div>
                </div>
                <div className="settings-field">
                  <div>
                    <span className="settings-field-label">API mode</span>
                    <span className="settings-field-hint">Configured by environment</span>
                  </div>
                  <div className="settings-field-value">
                    <span className={`status-pill ${apiMode === "live" ? "tone-success" : "tone-info"}`}>
                      {apiMode}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          ) : null}

          {tab === "organization" ? (
            <div className="settings-section">
              <header className="settings-section-head">
                <div>
                  <h3>Organization</h3>
                  <p>Active tenant context for directory, processes, and entitlements.</p>
                </div>
              </header>

              <div className="settings-org-card">
                <div>
                  <p className="eyebrow">Active workspace</p>
                  <h4>{activeOrganization?.name ?? "No organization selected"}</h4>
                  <p className="muted">
                    {activeOrganization?.slug ?? "—"} · {organizations.length} membership
                    {organizations.length === 1 ? "" : "s"}
                  </p>
                </div>
                <div className="settings-org-meta">
                  <div>
                    <span className="settings-field-label">Role</span>
                    <strong>{activeOrganization?.membership_role ?? "—"}</strong>
                  </div>
                  <div>
                    <span className="settings-field-label">Plan</span>
                    <strong>{planLabel(activeOrganization?.plan_code)}</strong>
                  </div>
                </div>
              </div>

              <div className="settings-link-grid">
                <Link to="/company" className="settings-link-card">
                  <strong>Company profile</strong>
                  <span>Legal name, tax, locale</span>
                </Link>
                <Link to="/billing" className="settings-link-card">
                  <strong>Billing & plans</strong>
                  <span>Entitlements and usage</span>
                </Link>
                <Link to="/employees" className="settings-link-card">
                  <strong>People directory</strong>
                  <span>Members and departments</span>
                </Link>
                <Link to="/organizations" className="settings-link-card">
                  <strong>Switch organization</strong>
                  <span>Change active tenant</span>
                </Link>
              </div>
            </div>
          ) : null}

          {tab === "notifications" ? (
            <div className="settings-section">
              <header className="settings-section-head">
                <div>
                  <h3>Notifications</h3>
                  <p>Browser-session preferences. Server delivery still follows org policy.</p>
                </div>
              </header>
              <div className="settings-toggle-list">
                <label className="settings-toggle">
                  <span>
                    <strong>Process status updates</strong>
                    <small>Alert when runs change state or need attention</small>
                  </span>
                  <input
                    type="checkbox"
                    checked={prefs.processUpdates}
                    onChange={(e) => {
                      setPrefs((p) => ({ ...p, processUpdates: e.target.checked }));
                      flash("Notification preferences updated");
                    }}
                  />
                </label>
                <label className="settings-toggle">
                  <span>
                    <strong>Approval requests</strong>
                    <small>Notify when you are a required approver</small>
                  </span>
                  <input
                    type="checkbox"
                    checked={prefs.approvalRequests}
                    onChange={(e) => {
                      setPrefs((p) => ({ ...p, approvalRequests: e.target.checked }));
                      flash("Notification preferences updated");
                    }}
                  />
                </label>
                <label className="settings-toggle">
                  <span>
                    <strong>Weekly digest</strong>
                    <small>Summary of completed and blocked work</small>
                  </span>
                  <input
                    type="checkbox"
                    checked={prefs.weeklyDigest}
                    onChange={(e) => {
                      setPrefs((p) => ({ ...p, weeklyDigest: e.target.checked }));
                      flash("Notification preferences updated");
                    }}
                  />
                </label>
              </div>
            </div>
          ) : null}

          {tab === "security" ? (
            <div className="settings-section">
              <header className="settings-section-head">
                <div>
                  <h3>Security</h3>
                  <p>Session controls and tenant scoping for this browser.</p>
                </div>
              </header>
              <div className="settings-field-list">
                <div className="settings-field">
                  <div>
                    <span className="settings-field-label">Auth provider</span>
                    <span className="settings-field-hint">How this session was established</span>
                  </div>
                  <div className="settings-field-value">{authProvider}</div>
                </div>
                <div className="settings-field">
                  <div>
                    <span className="settings-field-label">Tenant scoping</span>
                    <span className="settings-field-hint">
                      Organization access is validated server-side
                    </span>
                  </div>
                  <div className="settings-field-value">
                    <span className="status-pill tone-success">Membership checked</span>
                  </div>
                </div>
              </div>

              <div className="settings-danger">
                <div>
                  <h4>Sign out of this device</h4>
                  <p>Clears the local session token and returns you to login.</p>
                </div>
                <button type="button" className="danger-btn" onClick={() => void signOut()}>
                  Sign out
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
