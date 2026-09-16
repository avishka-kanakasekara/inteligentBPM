/** Minimal Supabase password auth — public anon key only (never service role). */

export type SupabaseSession = {
  accessToken: string;
  refreshToken: string | null;
  user: {
    id: string;
    email: string | null;
    displayName: string;
  };
};

export type SignUpResult =
  | { kind: "session"; session: SupabaseSession }
  | { kind: "confirm_email"; email: string; message: string };

function supabaseConfigured(): boolean {
  return Boolean(import.meta.env.VITE_SUPABASE_URL && import.meta.env.VITE_SUPABASE_ANON_KEY);
}

export function isSupabaseAuthEnabled(): boolean {
  return supabaseConfigured() && (import.meta.env.VITE_USE_MOCK_API ?? "true") === "false";
}

function parseSessionPayload(payload: unknown, fallbackEmail?: string): SupabaseSession {
  if (
    typeof payload !== "object" ||
    payload === null ||
    !("access_token" in payload) ||
    typeof (payload as { access_token?: unknown }).access_token !== "string"
  ) {
    throw new Error("Unexpected Supabase auth response");
  }

  const data = payload as {
    access_token: string;
    refresh_token?: string;
    user?: { id?: string; email?: string | null; user_metadata?: { full_name?: string } };
  };

  const userId = data.user?.id;
  if (!userId) {
    throw new Error("Supabase auth response missing user id");
  }

  const email = data.user?.email ?? fallbackEmail ?? null;
  const displayName =
    data.user?.user_metadata?.full_name || (email ? email.split("@")[0] : "User");

  return {
    accessToken: data.access_token,
    refreshToken: data.refresh_token ?? null,
    user: {
      id: userId,
      email,
      displayName,
    },
  };
}

function authErrorMessage(payload: unknown, fallback: string): string {
  if (typeof payload !== "object" || payload === null) return fallback;
  const data = payload as {
    error_description?: string;
    msg?: string;
    message?: string;
    error?: string;
  };
  return data.error_description || data.msg || data.message || data.error || fallback;
}

export async function signInWithPassword(
  email: string,
  password: string,
): Promise<SupabaseSession> {
  if (!supabaseConfigured()) {
    throw new Error("Supabase is not configured in the frontend environment");
  }

  const url = `${import.meta.env.VITE_SUPABASE_URL}/auth/v1/token?grant_type=password`;
  const response = await fetch(url, {
    method: "POST",
    headers: {
      apikey: import.meta.env.VITE_SUPABASE_ANON_KEY!,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ email, password }),
  });

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(authErrorMessage(payload, "Invalid email or password"));
  }

  return parseSessionPayload(payload, email);
}

export async function signUpWithPassword(input: {
  email: string;
  password: string;
  fullName: string;
}): Promise<SignUpResult> {
  if (!supabaseConfigured()) {
    throw new Error("Supabase is not configured in the frontend environment");
  }

  const url = `${import.meta.env.VITE_SUPABASE_URL}/auth/v1/signup`;
  const response = await fetch(url, {
    method: "POST",
    headers: {
      apikey: import.meta.env.VITE_SUPABASE_ANON_KEY!,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      email: input.email,
      password: input.password,
      data: { full_name: input.fullName },
    }),
  });

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(authErrorMessage(payload, "Could not create your account"));
  }

  if (
    typeof payload === "object" &&
    payload !== null &&
    "access_token" in payload &&
    typeof (payload as { access_token?: unknown }).access_token === "string"
  ) {
    return { kind: "session", session: parseSessionPayload(payload, input.email) };
  }

  return {
    kind: "confirm_email",
    email: input.email,
    message:
      "Account created. Check your email to confirm, then sign in to choose or create an organization.",
  };
}

/** Exchange a refresh token for a new access token. */
export async function refreshSession(refreshToken: string): Promise<SupabaseSession> {
  if (!supabaseConfigured()) {
    throw new Error("Supabase is not configured in the frontend environment");
  }

  const url = `${import.meta.env.VITE_SUPABASE_URL}/auth/v1/token?grant_type=refresh_token`;
  const response = await fetch(url, {
    method: "POST",
    headers: {
      apikey: import.meta.env.VITE_SUPABASE_ANON_KEY!,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error("Session expired — please sign in again");
  }

  return parseSessionPayload(payload);
}
