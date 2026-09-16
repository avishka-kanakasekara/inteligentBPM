import { Navigate, Route, Routes } from "react-router-dom";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { AppLayout } from "./components/layout/AppLayout";
import {
  GuestOnly,
  RequireAuth,
  RequireOrganization,
} from "./components/RouteGuards";
import { ApprovalsPage } from "./features/approvals/ApprovalsPage";
import { AuditLogPage } from "./features/audit/AuditLogPage";
import { BillingPage } from "./features/billing/BillingPage";
import { CompanyProfilePage } from "./features/company/CompanyProfilePage";
import { DashboardPage } from "./features/dashboard/DashboardPage";
import { DiscoveryChatPage } from "./features/discovery/DiscoveryChatPage";
import { EmployeesPage } from "./features/employees/EmployeesPage";
import { ExecutionHistoryPage } from "./features/history/ExecutionHistoryPage";
import { IntegrationsPage } from "./features/integrations/IntegrationsPage";
import { LoginPage } from "./features/login/LoginPage";
import { SignupPage } from "./features/login/SignupPage";
import { OrganizationSelectPage } from "./features/org-select/OrganizationSelectPage";
import { ProcessPlansPage } from "./features/plans/ProcessPlansPage";
import { PoliciesDocumentsPage } from "./features/policies/PoliciesDocumentsPage";
import { ActiveRunsPage } from "./features/runs/ActiveRunsPage";
import { SettingsPage } from "./features/settings/SettingsPage";
import { SuppliersPage } from "./features/suppliers/SuppliersPage";
import { WorkspacePage } from "./features/workspace/WorkspacePage";
import { EmptyState } from "./components/ui/EmptyState";

export function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route element={<GuestOnly />}>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/signup" element={<SignupPage />} />
        </Route>

        <Route element={<RequireAuth />}>
          <Route path="/organizations" element={<OrganizationSelectPage />} />

          <Route element={<RequireOrganization />}>
            <Route element={<AppLayout />}>
              <Route index element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/company" element={<CompanyProfilePage />} />
              <Route path="/employees" element={<EmployeesPage />} />
              <Route path="/suppliers" element={<SuppliersPage />} />
              <Route path="/policies" element={<PoliciesDocumentsPage />} />
              <Route path="/workspace" element={<WorkspacePage />} />
              <Route path="/discovery" element={<DiscoveryChatPage />} />
              <Route path="/plans" element={<ProcessPlansPage />} />
              <Route path="/approvals" element={<ApprovalsPage />} />
              <Route path="/runs" element={<ActiveRunsPage />} />
              <Route path="/history" element={<ExecutionHistoryPage />} />
              <Route path="/audit" element={<AuditLogPage />} />
              <Route path="/integrations" element={<IntegrationsPage />} />
              <Route path="/billing" element={<BillingPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Route>
          </Route>
        </Route>

        <Route
          path="*"
          element={
            <main className="page">
              <EmptyState
                title="Page not found"
                description="That route is not part of the application shell."
                action={
                  <a href="/dashboard" className="btn btn-primary">
                    Return to dashboard
                  </a>
                }
              />
            </main>
          }
        />
      </Routes>
    </ErrorBoundary>
  );
}
