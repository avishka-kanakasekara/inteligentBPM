import { NavLink, Outlet, useLocation } from "react-router-dom";
import { NotificationCenter } from "../notifications/NotificationCenter";
import { useAuth } from "../../providers/AuthProvider";
import { useOrganization } from "../../providers/OrganizationProvider";
import { PERMISSIONS } from "../../lib/permissions";

const NAV_GROUPS = [
  {
    label: "Core",
    items: [
      {
        to: "/dashboard",
        label: "Dashboard",
        icon: (
          <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="7" height="9" rx="1" />
            <rect x="14" y="3" width="7" height="5" rx="1" />
            <rect x="14" y="12" width="7" height="9" rx="1" />
            <rect x="3" y="16" width="7" height="5" rx="1" />
          </svg>
        ),
      },
      {
        to: "/company",
        label: "Company",
        icon: (
          <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
            <polyline points="9 22 9 12 15 12 15 22" />
          </svg>
        ),
      },
      {
        to: "/employees",
        label: "People",
        permission: PERMISSIONS.DIRECTORY_READ,
        icon: (
          <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
            <circle cx="9" cy="7" r="4" />
            <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
            <path d="M16 3.13a4 4 0 0 1 0 7.75" />
          </svg>
        ),
      },
      {
        to: "/suppliers",
        label: "Suppliers",
        permission: PERMISSIONS.SUPPLIERS_READ,
        icon: (
          <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
            <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
          </svg>
        ),
      },
      {
        to: "/policies",
        label: "Policies",
        permission: PERMISSIONS.POLICIES_READ,
        icon: (
          <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
            <polyline points="10 9 9 9 8 9" />
          </svg>
        ),
      },
    ],
  },
  {
    label: "Processes",
    items: [
      {
        to: "/workspace",
        label: "Workspace",
        permission: PERMISSIONS.PROCESSES_READ,
        icon: (
          <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
          </svg>
        ),
      },
      {
        to: "/discovery",
        label: "Discovery",
        feature: "process.discovery",
        icon: (
          <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
            <path d="M11 8v3l2 2" />
          </svg>
        ),
      },
      {
        to: "/plans",
        label: "Plans",
        permission: PERMISSIONS.PROCESSES_READ,
        icon: (
          <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21.5 12H16c-.7 2-2 3-4 3s-3.3-1-4-3H2.5" />
            <path d="M5.5 5.1L2 12v6c0 1.1.9 2 2 2h16a2 2 0 002-2v-6l-3.5-6.9A2 2 0 0016.7 4H7.3a2 2 0 00-1.8 1.1z" />
          </svg>
        ),
      },
      {
        to: "/approvals",
        label: "Approvals",
        permission: PERMISSIONS.APPROVALS_READ,
        icon: (
          <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
            <polyline points="22 4 12 14.01 9 11.01" />
          </svg>
        ),
      },
      {
        to: "/runs",
        label: "Active runs",
        permission: PERMISSIONS.PROCESSES_READ,
        icon: (
          <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
        ),
      },
      {
        to: "/history",
        label: "History",
        permission: PERMISSIONS.PROCESSES_READ,
        icon: (
          <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 3v5h5" />
            <path d="M3.05 13A9 9 0 1 0 6 5.3L3 8" />
            <path d="M12 7v5l4 2" />
          </svg>
        ),
      },
    ],
  },
  {
    label: "Administration",
    items: [
      {
        to: "/audit",
        label: "Audit",
        permission: PERMISSIONS.AUDIT_READ,
        icon: (
          <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
            <polyline points="10 9 9 9 8 9" />
          </svg>
        ),
      },
      {
        to: "/integrations",
        label: "Integrations",
        permission: PERMISSIONS.INTEGRATIONS_CONFIGURE,
        icon: (
          <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 8V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
            <rect x="10" y="8" width="12" height="8" rx="2" ry="2" />
          </svg>
        ),
      },
      {
        to: "/billing",
        label: "Billing",
        permission: PERMISSIONS.BILLING_MANAGE,
        icon: (
          <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="2" y="5" width="20" height="14" rx="2" />
            <line x1="2" y1="10" x2="22" y2="10" />
          </svg>
        ),
      },
      {
        to: "/settings",
        label: "Settings",
        icon: (
          <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        ),
      },
    ],
  },
];

const PAGE_TITLES: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/company": "Company",
  "/employees": "People",
  "/suppliers": "Suppliers",
  "/policies": "Policies",
  "/workspace": "Workspace",
  "/discovery": "Discovery",
  "/plans": "Plans",
  "/approvals": "Approvals",
  "/runs": "Active runs",
  "/history": "History",
  "/audit": "Audit log",
  "/integrations": "Integrations",
  "/billing": "Billing",
  "/settings": "Settings",
};

function initials(name?: string | null, email?: string | null) {
  const source = name?.trim() || email?.trim() || "US";
  return source.slice(0, 2).toUpperCase();
}

export function AppLayout() {
  const { user, signOut } = useAuth();
  const { activeOrganization, can, hasFeature } = useOrganization();
  const location = useLocation();
  const pageTitle = PAGE_TITLES[location.pathname] ?? "Workspace";

  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>

      <nav className="side-nav" aria-label="Primary">
        <div className="side-brand">
          <span className="brand-mark" aria-hidden="true" />
          <div>
            <div className="brand-name">Intelligent BPM</div>
            <div className="brand-org">{activeOrganization?.name ?? "No organization"}</div>
          </div>
        </div>

        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="nav-group">
            <div className="nav-group-label">{group.label}</div>
            <ul>
              {group.items.map((item) => {
                if ("permission" in item && item.permission && !can(item.permission as never)) {
                  return null;
                }
                if ("feature" in item && item.feature && !hasFeature(item.feature)) {
                  return null;
                }
                return (
                  <li key={item.to}>
                    <NavLink to={item.to} aria-current={location.pathname === item.to ? "page" : undefined}>
                      {item.icon}
                      <span>{item.label}</span>
                    </NavLink>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}

        <div className="side-footer">
          <div className="side-user">
            <div className="avatar-disk" aria-hidden="true">
              {initials(user?.displayName, user?.email)}
            </div>
            <div style={{ minWidth: 0 }}>
              <div className="session-user">{user?.displayName || user?.email}</div>
              <div className="brand-org">{activeOrganization?.membership_role ?? "member"}</div>
            </div>
          </div>
          <NavLink to="/organizations" className="org-switch-link">
            Switch organization
          </NavLink>
          <button type="button" className="ghost-btn" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </nav>

      <header className="topbar">
        <div className="topbar-context">
          <div className="breadcrumbs" aria-label="Breadcrumb">
            <span>{activeOrganization?.name ?? "Organization"}</span>
            <span aria-hidden="true">/</span>
            <strong>{pageTitle}</strong>
          </div>
          <p className="topbar-org">Discover · Allocate · Approve · Execute</p>
        </div>
        <div className="topbar-actions">
          <NotificationCenter />
          <NavLink to="/organizations" className="org-switch-link">
            Switch org
          </NavLink>
          <div className="side-user" style={{ padding: 0 }}>
            <div className="avatar-disk" aria-hidden="true">
              {initials(user?.displayName, user?.email)}
            </div>
            <span className="session-user">{user?.displayName}</span>
          </div>
        </div>
      </header>

      <div className="layout-main">
        <main id="main-content" className="page">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
