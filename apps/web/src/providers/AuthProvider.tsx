import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { User } from "@bpm/frontend-types";
import {
  isSupabaseAuthEnabled,
  signInWithPassword,
  signUpWithPassword,
  updateDisplayName,
} from "../lib/supabaseAuth";
import { findMockAccount, resolveLocalAccount, saveMockAccount } from "../lib/mockAccounts";
import { sessionStore } from "../lib/sessionStore";

export type SignUpOutcome =
  | { kind: "signed_in" }
  | { kind: "confirm_email"; email: string; message: string };

type AuthContextValue = {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (input: {
    email: string;
    password: string;
    fullName: string;
  }) => Promise<SignUpOutcome>;
  signOut: () => Promise<void>;
  updateProfile: (input: { displayName: string }) => Promise<void>;
  authError: string | null;
  clearAuthError: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

type AuthProviderProps = {
  children: ReactNode;
};

function applySession(user: User, accessToken: string, refreshToken: string | null) {
  sessionStore.setUser(user);
  sessionStore.setToken(accessToken);
  sessionStore.setRefreshToken(refreshToken);
}

function shareDemoAccount(): boolean {
  return (import.meta.env.VITE_USE_MOCK_API ?? "true") !== "false";
}

/**
 * Auth provider — Supabase password login/signup when the real API is enabled;
 * foundation mock token for local mock-api mode only.
 */
export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(() => sessionStore.getUser());
  const [token, setToken] = useState<string | null>(() => sessionStore.getToken());
  const [isLoading, setIsLoading] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  const clearAuthError = useCallback(() => setAuthError(null), []);

  const signIn = useCallback(async (email: string, password: string) => {
    setIsLoading(true);
    setAuthError(null);
    try {
      if (isSupabaseAuthEnabled()) {
        const session = await signInWithPassword(email, password);
        const nextUser: User = {
          id: session.user.id,
          email: session.user.email ?? email,
          displayName: session.user.displayName,
        };
        applySession(nextUser, session.accessToken, session.refreshToken);
        setUser(nextUser);
        setToken(session.accessToken);
        return;
      }

      const nextUser: User = resolveLocalAccount(email, shareDemoAccount());
      const nextToken = `mock-access-token:${nextUser.id}`;
      applySession(nextUser, nextToken, null);
      setUser(nextUser);
      setToken(nextToken);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Sign in failed";
      setAuthError(message);
      throw error;
    } finally {
      setIsLoading(false);
    }
  }, []);

  const signUp = useCallback(
    async (input: { email: string; password: string; fullName: string }) => {
      setIsLoading(true);
      setAuthError(null);
      try {
        if (isSupabaseAuthEnabled()) {
          const result = await signUpWithPassword(input);
          if (result.kind === "confirm_email") {
            return {
              kind: "confirm_email" as const,
              email: result.email,
              message: result.message,
            };
          }
          const session = result.session;
          const nextUser: User = {
            id: session.user.id,
            email: session.user.email ?? input.email,
            displayName: session.user.displayName || input.fullName,
          };
          applySession(nextUser, session.accessToken, session.refreshToken);
          setUser(nextUser);
          setToken(session.accessToken);
          return { kind: "signed_in" as const };
        }

        const existing = findMockAccount(input.email);
        const nextUser: User = existing ?? {
          id: crypto.randomUUID(),
          email: input.email,
          displayName: input.fullName || input.email.split("@")[0] || "User",
        };
        saveMockAccount(nextUser);
        const nextToken = `mock-access-token:${nextUser.id}`;
        applySession(nextUser, nextToken, null);
        setUser(nextUser);
        setToken(nextToken);
        return { kind: "signed_in" as const };
      } catch (error) {
        const message = error instanceof Error ? error.message : "Sign up failed";
        setAuthError(message);
        throw error;
      } finally {
        setIsLoading(false);
      }
    },
    [],
  );

  const updateProfile = useCallback(
    async (input: { displayName: string }) => {
      const displayName = input.displayName.trim().replace(/\s+/g, " ");
      if (!user || !token) throw new Error("Sign in before updating your profile");
      if (!displayName) throw new Error("Display name is required");
      if (displayName.length > 80) throw new Error("Display name must be 80 characters or fewer");

      const mockSession = token.startsWith("mock-access-token:");
      if (isSupabaseAuthEnabled() && !mockSession) {
        await updateDisplayName(token, displayName);
      } else {
        saveMockAccount({ id: user.id, email: user.email, displayName });
      }

      const nextUser: User = { ...user, displayName };
      sessionStore.setUser(nextUser);
      setUser(nextUser);
    },
    [token, user],
  );

  const signOut = useCallback(async () => {
    setIsLoading(true);
    try {
      sessionStore.clear();
      setUser(null);
      setToken(null);
      setAuthError(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      isAuthenticated: Boolean(user && token),
      isLoading,
      signIn,
      signUp,
      signOut,
      updateProfile,
      authError,
      clearAuthError,
    }),
    [user, token, isLoading, signIn, signUp, signOut, updateProfile, authError, clearAuthError],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
