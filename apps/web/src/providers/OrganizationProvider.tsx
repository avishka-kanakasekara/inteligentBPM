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
import { permissionsForRole, planHasFeature, type Permission } from "../lib/permissions";
import { sessionStore } from "../lib/sessionStore";
import { useAuth } from "./AuthProvider";

type OrganizationContextValue = {
  organizations: Organization[];
  activeOrganization: Organization | null;
  isLoading: boolean;
  error: Error | null;
  setActiveOrganizationId: (id: string) => void;
  can: (permission: Permission) => boolean;
  hasFeature: (feature: string) => boolean;
  refetch: () => void;
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

  const organizations = query.data ?? [];
  const activeOrganization =
    organizations.find((org) => org.id === activeId) ?? organizations[0] ?? null;

  if (activeOrganization && sessionStore.getOrganizationId() !== activeOrganization.id) {
    sessionStore.setOrganizationId(activeOrganization.id);
  }

  useEffect(() => {
    if (activeOrganization && activeId !== activeOrganization.id) {
      setActiveId(activeOrganization.id);
    }
  }, [activeOrganization, activeId]);

  const setActiveOrganizationId = useCallback((id: string) => {
    sessionStore.setOrganizationId(id);
    setActiveId(id);
  }, []);

  const value = useMemo<OrganizationContextValue>(
    () => ({
      organizations,
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
      refetch: () => {
        void query.refetch();
      },
    }),
    [organizations, activeOrganization, query, setActiveOrganizationId],
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
