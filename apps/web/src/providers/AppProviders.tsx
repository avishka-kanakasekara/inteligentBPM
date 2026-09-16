import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { AuthProvider } from "./AuthProvider";
import { NotificationProvider } from "./NotificationProvider";
import { OrganizationProvider } from "./OrganizationProvider";

export function AppProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: false,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <OrganizationProvider>
          <NotificationProvider>{children}</NotificationProvider>
        </OrganizationProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
