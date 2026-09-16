import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../providers/AuthProvider";
import { useOrganization } from "../providers/OrganizationProvider";
import { LoadingState } from "../components/ui/LoadingState";
import type { Permission } from "../lib/permissions";

export function RequireAuth() {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) return <LoadingState label="Checking session…" />;
  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
}

export function RequireOrganization() {
  const { activeOrganization, organizations, isLoading } = useOrganization();
  const location = useLocation();

  if (isLoading) return <LoadingState label="Loading organizations…" />;
  if (!organizations.length) {
    return <Navigate to="/organizations" replace />;
  }
  if (!activeOrganization && location.pathname !== "/organizations") {
    return <Navigate to="/organizations" replace />;
  }
  return <Outlet />;
}

export function RequirePermission({
  permission,
  children,
  fallback = null,
}: {
  permission: Permission;
  children: React.ReactNode;
  fallback?: React.ReactNode;
}) {
  const { can } = useOrganization();
  if (!can(permission)) return <>{fallback}</>;
  return <>{children}</>;
}

export function RequireFeature({
  feature,
  children,
  fallback = null,
}: {
  feature: string;
  children: React.ReactNode;
  fallback?: React.ReactNode;
}) {
  const { hasFeature } = useOrganization();
  if (!hasFeature(feature)) return <>{fallback}</>;
  return <>{children}</>;
}

export function GuestOnly() {
  const { isAuthenticated } = useAuth();
  const location = useLocation();
  if (location.search.includes("logout=true")) return <Outlet />;
  if (isAuthenticated) return <Navigate to="/organizations" replace />;
  return <Outlet />;
}
