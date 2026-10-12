import { useQuery } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { Organization } from "@bpm/frontend-types";
import { apiClient } from "../lib/apiClient";
import { authorizedOrganizationId } from "../lib/organizationDisplay";
import { permissionsForRole, planHasFeature, type Permission } from "../lib/permissions";
import { sessionStore } from "../lib/sessionStore";
import { useAuth } from "./AuthProvider";

type OrganizationContextValue = {
  organizations: Organization[];
  canCreateOrganization: boolean;
  activeOrganization: Organization | null;
  isLoading: boolean;
  error: Error | null;
  setActiveOrganizationId: (id: string, knownOrganizations?: Organization[]) => void;
  can: (permission: Permission) => boolean;
  hasFeature: (feature: string) => boolean;
  refetch: () => Promise<{ data?: Organization[] }>;
};

const OrganizationContext = createContext<OrganizationContextValue | null>(null);

export function OrganizationProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  const [activeId, setActiveId] = useState<string | null>(() =>
    sessionStore.getOrganizationId(),
  );

  const query = useQuery({
    queryKey: ["organizations"],
    queryFn: () => apiClient.listOrganizations(),
    enabled: isAuthenticated,
    retry: (failureCount, error) => {
      if (error instanceof Error && "status" in error && (error as { status?: number }).status === 401) {
        return false;
      }
      return failureCount < 2;
    },
  });

  const organizations = query.data?.organizations ?? [];
  const canCreateOrganization = query.data?.canCreateOrganization ?? true;
  const activeOrganization =
    organizations.find((org) => org.id === activeId) ?? organizations[0] ?? null;

  useEffect(() => {
    if (!query.isSuccess) return;
    const allowed = query.data?.organizations ?? [];
    const stored = sessionStore.getOrganizationId();
    const selected =
      allowed.find((org) => org.id === stored)?.id ?? allowed[0]?.id ?? null;
    if (selected) {
      if (stored !== selected) sessionStore.setOrganizationId(selected);
      if (activeId !== selected) setActiveId(selected);
      return;
    }
    if (stored) sessionStore.setOrganizationId(null);
    if (activeId) setActiveId(null);
  }, [query.isSuccess, query.data, activeId]);

  const setActiveOrganizationId = useCallback(
    (id: string, knownOrganizations?: Organization[]) => {
      const allowed = authorizedOrganizationId(id, knownOrganizations ?? organizations);
      if (!allowed) return;
      sessionStore.setOrganizationId(allowed);
      setActiveId(allowed);
    },
    [organizations],
  );

  const value = useMemo<OrganizationContextValue>(
    () => ({
      organizations,
      canCreateOrganization,
      activeOrganization,
      isLoading: query.isLoading,
      error: query.error,
      setActiveOrganizationId,
      can: (permission) =>
        activeOrganization
          ? permissionsForRole(activeOrganization.membership_role).has(permission)
          : false,
      hasFeature: (feature) =>
        activeOrganization
          ? planHasFeature(activeOrganization.plan_code, feature)
          : false,
      refetch: async () => {
        const result = await query.refetch();
        return { data: result.data?.organizations };
      },
    }),
    [organizations, canCreateOrganization, activeOrganization, query, setActiveOrganizationId],
  );

  return (
    <OrganizationContext.Provider value={value}>{children}</OrganizationContext.Provider>
  );
}

export function useOrganization(): OrganizationContextValue {
  const context = useContext(OrganizationContext);
  if (!context) throw new Error("useOrganization must be used within OrganizationProvider");
  return context;
}
