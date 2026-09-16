import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { EmptyState } from "../../components/ui/EmptyState";
import { LoadingState } from "../../components/ui/LoadingState";
import { RetryState } from "../../components/ui/RetryState";
import { apiClient } from "../../lib/apiClient";
import { useAuth } from "../../providers/AuthProvider";
import { useOrganization } from "../../providers/OrganizationProvider";

export function OrganizationSelectPage() {
  const navigate = useNavigate();
  const { signOut, user } = useAuth();
  const {
    organizations,
    activeOrganization,
    setActiveOrganizationId,
    isLoading,
    error,
    refetch,
  } = useOrganization();

  const [newOrgName, setNewOrgName] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const handleSignOut = async () => {
    await signOut();
    navigate("/login?logout=true", { replace: true });
  };

  const handleCreateOrg = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newOrgName.trim()) return;
    setIsCreating(true);
    setCreateError(null);
    try {
      const created = await apiClient.createOrganization({
        name: newOrgName.trim(),
        plan_code: "pro",
      });
      await refetch();
      setActiveOrganizationId(created.id);
      navigate("/dashboard");
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : "Failed to create organization");
    } finally {
      setIsCreating(false);
    }
  };

  if (isLoading) return <LoadingState label="Loading organizations…" />;
  if (error) {
    return <RetryState message={error.message} onRetry={() => refetch()} />;
  }

  return (
    <main className="auth-stage org-stage">
      <section className="org-workspace" aria-labelledby="org-title">
        <aside className="org-intro">
          <span className="brand-mark" aria-hidden="true" />
          <p className="auth-brand-name">Intelligent BPM</p>
          <h1 id="org-title">Select organization</h1>
          <p className="auth-subtitle">
            Signed in as <strong>{user?.displayName || user?.email}</strong>
            {user?.email ? ` · ${user.email}` : ""}. Choose a workspace to continue operations.
          </p>
          <button type="button" className="ghost-btn" style={{ marginTop: "1.25rem" }} onClick={() => void handleSignOut()}>
            Sign out
          </button>
        </aside>

        <div className="org-main">
          {organizations.length > 0 ? (
            <ul className="org-pick-list">
              {organizations.map((org) => (
                <li key={org.id}>
                  <button
                    type="button"
                    className={org.id === activeOrganization?.id ? "org-pick selected" : "org-pick"}
                    onClick={() => {
                      setActiveOrganizationId(org.id);
                      navigate("/dashboard");
                    }}
                  >
                    <span>
                      <strong>{org.name}</strong>
                      <span className="muted tight">
                        {org.plan_code} · {org.membership_role}
                      </span>
                    </span>
                    <span className="org-enter">Enter</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No organizations yet"
              description="Create your company workspace below to start discovery and execution."
            />
          )}

          <form className="org-create" onSubmit={(e) => void handleCreateOrg(e)}>
            <h2>Create a company instance</h2>
            <p className="muted">
              Sets up a tenant workspace for employees, suppliers, policies, and agent runs.
            </p>
            {createError ? (
              <p className="field-error" role="alert">
                {createError}
              </p>
            ) : null}
            <div className="org-create-row">
              <input
                id="org-name-input"
                type="text"
                value={newOrgName}
                onChange={(e) => setNewOrgName(e.target.value)}
                placeholder="e.g. Acme Corporation"
                required
                disabled={isCreating}
                aria-label="Organization name"
              />
              <button type="submit" disabled={isCreating || !newOrgName.trim()}>
                {isCreating ? "Creating…" : "Create & enter"}
              </button>
            </div>
          </form>
        </div>
      </section>
    </main>
  );
}
