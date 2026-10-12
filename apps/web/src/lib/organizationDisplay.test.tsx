import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { Organization } from "@bpm/frontend-types";
import { OrganizationSelectPage } from "../features/org-select/OrganizationSelectPage";
import {
  authorizedOrganizationId,
  organizationDisplayName,
  organizationPlanLabel,
} from "./organizationDisplay";
import { planHasFeature } from "./permissions";

const { selectOrganization, hostedOrg, memoryOrg, hostedId } = vi.hoisted(() => {
  const hostedId = "76ec608f-37a4-45fa-bb58-fb81c0710720";
  const otherId = "11111111-1111-1111-1111-111111111111";
  const hostedOrg = {
    id: hostedId,
    name: "",
    slug: "",
    plan_code: null,
    status: "",
    membership_role: "employee",
  } as Organization;
  const memoryOrg = {
    id: otherId,
    name: "Demo Organization",
    slug: "demo-organization",
    plan_code: "pro",
    status: "active",
    membership_role: "owner",
  } as Organization;
  return { selectOrganization: vi.fn(), hostedOrg, memoryOrg, hostedId };
});

vi.mock("../providers/AuthProvider", () => ({
  useAuth: () => ({
    user: { id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", email: "ada@example.com", displayName: "Ada" },
    signOut: vi.fn(),
  }),
}));

vi.mock("../providers/OrganizationProvider", () => ({
  useOrganization: () => ({
    organizations: [hostedOrg, memoryOrg],
    canCreateOrganization: true,
    activeOrganization: hostedOrg,
    isLoading: false,
    error: null,
    setActiveOrganizationId: selectOrganization,
    can: () => false,
    hasFeature: () => false,
    refetch: vi.fn(),
  }),
}));

describe("hosted organization display", () => {
  it("shows Workspace when the tenant name is blank and omits an unspecified plan", () => {
    expect(organizationDisplayName(hostedOrg)).toBe("Workspace");
    expect(organizationPlanLabel(hostedOrg.plan_code)).toBeNull();
    expect(organizationDisplayName(memoryOrg)).toBe("Demo Organization");
    expect(organizationPlanLabel(memoryOrg.plan_code)).toBe("pro");
    expect(planHasFeature(null, "integrations.advanced")).toBe(false);
    expect(planHasFeature("enterprise", "integrations.advanced")).toBe(true);
  });

  it("renders the authorized list without assigning a paid plan", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <OrganizationSelectPage />
      </MemoryRouter>,
    );
    expect(screen.getByRole("button", { name: /workspace/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /demo organization/i })).toBeInTheDocument();
    expect(screen.queryByText(/pro · employee/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /workspace/i }));
    expect(selectOrganization).toHaveBeenCalledWith(hostedId);
  });

  it("rejects a tenant that is not in the authorized organization list", () => {
    const foreign = "22222222-2222-2222-2222-222222222222";
    expect(authorizedOrganizationId(hostedId, [hostedOrg, memoryOrg])).toBe(hostedId);
    expect(authorizedOrganizationId(foreign, [hostedOrg, memoryOrg])).toBeNull();
  });
});
