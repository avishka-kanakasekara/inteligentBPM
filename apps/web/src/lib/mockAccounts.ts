const ACCOUNTS_KEY = "bpm.mock_accounts";

export type MockAccount = {
  id: string;
  email: string;
  displayName: string;
};

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
