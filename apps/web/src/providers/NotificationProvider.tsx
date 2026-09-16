import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { Notification } from "@bpm/frontend-types";
import { apiClient } from "../lib/apiClient";
import { mockApi } from "../lib/mockApi";
import { useAuth } from "./AuthProvider";
import { useOrganization } from "./OrganizationProvider";

type NotificationContextValue = {
  notifications: Notification[];
  unreadCount: number;
  markRead: (id: string) => void;
  markAllRead: () => void;
};

const NotificationContext = createContext<NotificationContextValue | null>(null);

function useMockNotifications(): boolean {
  return (import.meta.env.VITE_USE_MOCK_API ?? "true") !== "false";
}

export function NotificationProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  const { activeOrganization } = useOrganization();
  const [notifications, setNotifications] = useState<Notification[]>(() =>
    useMockNotifications() ? mockApi.notifications : [],
  );

  useEffect(() => {
    if (!isAuthenticated || !activeOrganization || useMockNotifications()) {
      if (useMockNotifications()) {
        setNotifications(mockApi.notifications);
      }
      return;
    }
    let cancelled = false;
    void apiClient
      .listNotifications()
      .then((items) => {
        if (!cancelled) setNotifications(items);
      })
      .catch(() => {
        if (!cancelled) setNotifications([]);
      });
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, activeOrganization?.id]);

  const markRead = useCallback(
    (id: string) => {
      setNotifications((prev) =>
        prev.map((n) => (n.id === id ? { ...n, status: "read" } : n)),
      );
      if (!useMockNotifications()) {
        void apiClient.markNotificationRead(id).catch(() => undefined);
      }
    },
    [],
  );

  const markAllRead = useCallback(() => {
    setNotifications((prev) => {
      if (!useMockNotifications()) {
        for (const n of prev) {
          if (n.status === "unread") {
            void apiClient.markNotificationRead(n.id).catch(() => undefined);
          }
        }
      }
      return prev.map((n) => ({ ...n, status: "read" }));
    });
  }, []);

  const value = useMemo(
    () => ({
      notifications,
      unreadCount: notifications.filter((n) => n.status === "unread").length,
      markRead,
      markAllRead,
    }),
    [notifications, markRead, markAllRead],
  );

  return (
    <NotificationContext.Provider value={value}>{children}</NotificationContext.Provider>
  );
}

export function useNotifications(): NotificationContextValue {
  const context = useContext(NotificationContext);
  if (!context) throw new Error("useNotifications must be used within NotificationProvider");
  return context;
}
