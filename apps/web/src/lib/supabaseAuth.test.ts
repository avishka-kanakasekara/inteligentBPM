import { afterEach, describe, expect, it, vi } from "vitest";
import {
  EMAIL_CONFIRMATION_REQUIRED,
  signInWithPassword,
  signUpWithPassword,
} from "./supabaseAuth";

const password = "Signup9login";
const email = "friend@example.com";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("supabase password signup and login", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("sends the same unmodified password to signup and login on one project", async () => {
    vi.stubEnv("VITE_SUPABASE_URL", "https://auth.example.test");
    vi.stubEnv("VITE_SUPABASE_ANON_KEY", "anon-test-key");
    const bodies: Array<{ url: string; password: string; email: string }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const payload = JSON.parse(String(init?.body)) as { email: string; password: string };
        bodies.push({ url, email: payload.email, password: payload.password });
        if (url.includes("/signup")) {
          return jsonResponse({
            id: "11111111-1111-1111-1111-111111111111",
            email,
            confirmation_sent_at: "2026-10-09T00:00:00Z",
            identities: [{ provider: "email" }],
          });
        }
        return jsonResponse(
          { code: 400, error_code: "email_not_confirmed", msg: "Email not confirmed" },
          400,
        );
      }),
    );

    const created = await signUpWithPassword({
      email,
      password,
      fullName: "Friend Example",
    });
    expect(created.kind).toBe("confirm_email");

    await expect(signInWithPassword(email, password)).rejects.toThrow(EMAIL_CONFIRMATION_REQUIRED);

    expect(bodies).toHaveLength(2);
    expect(bodies[0]?.password).toBe(password);
    expect(bodies[1]?.password).toBe(password);
    expect(bodies[0]?.password).toHaveLength(password.length);
    expect(bodies[0]?.email).toBe(email);
    expect(bodies[1]?.email).toBe(email);
    expect(new URL(bodies[0]!.url).origin).toBe(new URL(bodies[1]!.url).origin);
    expect(bodies[0]?.url).toContain("/auth/v1/signup");
    expect(bodies[1]?.url).toContain("/auth/v1/token?grant_type=password");
  });

  it("does not start a session when signup only asks for email confirmation", async () => {
    vi.stubEnv("VITE_SUPABASE_URL", "https://auth.example.test");
    vi.stubEnv("VITE_SUPABASE_ANON_KEY", "anon-test-key");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          id: "11111111-1111-1111-1111-111111111111",
          email,
          identities: [{ provider: "email" }],
        }),
      ),
    );

    const created = await signUpWithPassword({ email, password, fullName: "Friend Example" });
    expect(created.kind).toBe("confirm_email");
    if (created.kind === "confirm_email") {
      expect(created.message.toLowerCase()).toContain("confirm");
      expect(created.message.toLowerCase()).not.toContain("email confirmed");
    }
  });

  it("does not treat an empty identity list as a signed-in account", async () => {
    vi.stubEnv("VITE_SUPABASE_URL", "https://auth.example.test");
    vi.stubEnv("VITE_SUPABASE_ANON_KEY", "anon-test-key");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          id: "22222222-2222-2222-2222-222222222222",
          email,
          identities: [],
        }),
      ),
    );

    const created = await signUpWithPassword({ email, password, fullName: "Friend Example" });
    expect(created.kind).toBe("confirm_email");
  });
});
