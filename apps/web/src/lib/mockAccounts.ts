const ACCOUNTS_KEY = "bpm.mock_accounts";

/** Seeded API owner. Only this account should see the sample company. */
export const DEMO_USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
export const DEMO_OWNER_EMAIL = "owner@demo.bpm.local";

export type MockAccount = {
  id: string;
  email: string;
  displayName: string;
};

/**
 * Local login identity when Supabase is not configured.
 * Mock-api mode keeps unknown emails on the shared demo account (existing tests).
 * The real API must not do that, or every login sees the seeded processes.
 */
export function resolveLocalAccount(email: string, shareDemoAccount: boolean): MockAccount {
  const stored = findMockAccount(email);
  if (stored) return stored;

  const normalized = email.trim().toLowerCase();
  const displayName = normalized.split("@")[0] || "User";
  if (shareDemoAccount || normalized === DEMO_OWNER_EMAIL) {
    return {
      id: DEMO_USER_ID,
      email: email.trim(),
      displayName,
    };
  }

  const created: MockAccount = {
    id: crypto.randomUUID(),
    email: email.trim(),
    displayName,
  };
  saveMockAccount(created);
  return created;
}

function readAccounts(): Record<string, MockAccount> {
  try {
    const raw = localStorage.getItem(ACCOUNTS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, MockAccount>;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

export function findMockAccount(email: string): MockAccount | null {
  return readAccounts()[email.trim().toLowerCase()] ?? null;
}

export function saveMockAccount(account: MockAccount): void {
  const all = readAccounts();
  const email = account.email.trim().toLowerCase();
  all[email] = { ...account, email: account.email.trim() };
  localStorage.setItem(ACCOUNTS_KEY, JSON.stringify(all));
}
