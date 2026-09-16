/** Session storage for auth tokens — never stores service-role or secret keys. */

const TOKEN_KEY = "bpm.access_token";
const REFRESH_KEY = "bpm.refresh_token";
const USER_KEY = "bpm.user";
const ORG_KEY = "bpm.organization_id";

export type StoredUser = {
  id: string;
  email: string;
  displayName: string;
};

export const sessionStore = {
  getToken(): string | null {
    return localStorage.getItem(TOKEN_KEY);
  },
  setToken(token: string | null): void {
    if (!token) localStorage.removeItem(TOKEN_KEY);
    else localStorage.setItem(TOKEN_KEY, token);
  },
  getRefreshToken(): string | null {
    return localStorage.getItem(REFRESH_KEY);
  },
  setRefreshToken(token: string | null): void {
    if (!token) localStorage.removeItem(REFRESH_KEY);
    else localStorage.setItem(REFRESH_KEY, token);
  },
  getUser(): StoredUser | null {
    const raw = localStorage.getItem(USER_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw) as StoredUser;
    } catch {
      return null;
    }
  },
  setUser(user: StoredUser | null): void {
    if (!user) localStorage.removeItem(USER_KEY);
    else localStorage.setItem(USER_KEY, JSON.stringify(user));
  },
  getOrganizationId(): string | null {
    return localStorage.getItem(ORG_KEY);
  },
  setOrganizationId(id: string | null): void {
    if (!id) localStorage.removeItem(ORG_KEY);
    else localStorage.setItem(ORG_KEY, id);
  },
  clear(): void {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(ORG_KEY);
  },
};
