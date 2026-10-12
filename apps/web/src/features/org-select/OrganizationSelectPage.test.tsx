import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { Organization } from "@bpm/frontend-types";
import { OrganizationSelectPage } from "./OrganizationSelectPage";

const directory = vi.hoisted(() => ({
  organizations: [] as Organization[],
  canCreateOrganization: true,
}));

vi.mock("../../providers/AuthProvider", () => ({
  useAuth: () => ({
    user: { id: "user-1", email: "ada@example.com", displayName: "Ada" },
    signOut: vi.fn(),
  }),
}));

vi.mock("../../providers/OrganizationProvider", () => ({
  useOrganization: () => ({
    organizations: directory.organizations,
    canCreateOrganization: directory.canCreateOrganization,
    activeOrganization: directory.organizations[0] ?? null,
    isLoading: false,
    error: null,
    setActiveOrganizationId: vi.fn(),
    can: () => false,
    hasFeature: () => false,
    refetch: vi.fn(),
  }),
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <OrganizationSelectPage />
    </MemoryRouter>,
  );
}

describe("organization selection", () => {
  it("hides creation when the server says organization creation is unsupported", () => {
    directory.organizations = [];
    directory.canCreateOrganization = false;
    renderPage();

    expect(screen.getByRole("heading", { name: "No workspace assigned" })).toBeInTheDocument();
    expect(
      screen.getByText(/an administrator must grant access before you can continue/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Create a company instance" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Organization name")).not.toBeInTheDocument();
    expect(screen.queryByText(/ORGANIZATION_CREATE_UNSUPPORTED/)).not.toBeInTheDocument();
    expect(screen.queryByText(/public\.organizations/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/422/)).not.toBeInTheDocument();
  });

  it("keeps organization creation when the server supports it", () => {
    directory.organizations = [];
    directory.canCreateOrganization = true;
    renderPage();

    expect(screen.getByRole("heading", { name: "Create a company instance" })).toBeInTheDocument();
    expect(screen.getByLabelText("Organization name")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create & enter" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "No workspace assigned" })).not.toBeInTheDocument();
  });
});
