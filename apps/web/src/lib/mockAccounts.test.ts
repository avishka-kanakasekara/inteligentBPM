import { beforeEach, describe, expect, it } from "vitest";
import { DEMO_OWNER_EMAIL, DEMO_USER_ID, resolveLocalAccount } from "./mockAccounts";

describe("resolveLocalAccount", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("keeps unknown emails on the demo account only in mock-api mode", () => {
    const account = resolveLocalAccount("alex@demo.test", true);
    expect(account.id).toBe(DEMO_USER_ID);
  });

  it("gives a new real-api login an empty identity instead of the seeded owner", () => {
    const first = resolveLocalAccount("new.person@example.com", false);
    const second = resolveLocalAccount("new.person@example.com", false);

    expect(first.id).not.toBe(DEMO_USER_ID);
    expect(second.id).toBe(first.id);
  });

  it("still maps the demo owner email to the seeded account", () => {
    const account = resolveLocalAccount(DEMO_OWNER_EMAIL, false);
    expect(account.id).toBe(DEMO_USER_ID);
  });
});
