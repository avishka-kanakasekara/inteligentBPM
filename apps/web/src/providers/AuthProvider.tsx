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
} from "../lib/supabaseAuth";
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

      // Mock-api / local demo — pairs with backend mock-access-token bypass
      const nextUser: User = {
        id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        email,
        displayName: email.split("@")[0] || "User",
      };
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

        // Mock mode — create a local session immediately
        const nextUser: User = {
          id: crypto.randomUUID(),
          email: input.email,
          displayName: input.fullName || input.email.split("@")[0] || "User",
        };
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
      authError,
      clearAuthError,
    }),
    [user, token, isLoading, signIn, signUp, signOut, authError, clearAuthError],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
