import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, beforeEach } from "vitest";
import { App } from "./App";
import { apiClient, ApiError } from "./lib/apiClient";
import { sessionStore } from "./lib/sessionStore";
import { AppProviders } from "./providers/AppProviders";

function renderApp(initialPath = "/") {
  return render(
    <AppProviders>
      <MemoryRouter
        initialEntries={[initialPath]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <App />
      </MemoryRouter>
    </AppProviders>,
  );
}

async function signInAsOwner() {
  const user = userEvent.setup();
  renderApp("/login");
  await user.type(screen.getByLabelText(/work email/i), "alex@demo.test");
  await user.type(screen.getByLabelText(/^password$/i), "password123");
  await user.click(screen.getByRole("button", { name: /^sign in$/i }));
  await user.click(await screen.findByRole("button", { name: /demo organization/i }));
  expect(await screen.findByRole("heading", { name: /dashboard/i })).toBeInTheDocument();
  return user;
}

beforeEach(() => {
  sessionStore.clear();
  localStorage.clear();
});

describe("organization management UI", () => {
  it("loads company profile fields for an admin", async () => {
    const user = await signInAsOwner();
    await user.click(screen.getByRole("link", { name: /company/i }));
    expect(await screen.findByRole("heading", { name: /company profile/i })).toBeInTheDocument();
    expect(await screen.findByLabelText(/legal name/i)).toHaveValue("Demo Organization LLC");
    expect(screen.getByLabelText(/timezone/i)).toHaveValue("UTC");
  });

  it("lists employees with search and shows import panel for managers", async () => {
    const user = await signInAsOwner();
    await user.click(screen.getByRole("link", { name: /^people$/i }));
    expect(await screen.findByRole("heading", { name: /employees and managers/i })).toBeInTheDocument();
    expect(await screen.findByText(/alex owner/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /import employees/i })).toBeInTheDocument();
  });

  it("shows supplier approval status and empty/loading-safe states", async () => {
    const user = await signInAsOwner();
    await user.click(screen.getByRole("link", { name: /^suppliers$/i }));
    expect(await screen.findByRole("heading", { name: /^suppliers$/i })).toBeInTheDocument();
    expect(await screen.findByText(/northwind supplies/i)).toBeInTheDocument();
    expect(screen.getAllByText(/approved/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/pending/i).length).toBeGreaterThan(0);
  });
});

describe("organization management API client", () => {
  it("detects duplicate employee emails on import preview", async () => {
    const preview = await apiClient.previewEmployeeImport(
      "full_name,email\nAlex Owner,alex@demo.test\n",
    );
    expect(preview.duplicate_count).toBeGreaterThan(0);
    expect(preview.duplicates[0].code).toBe("DUPLICATE_ACTIVE");
  });

  it("rejects commit when import has duplicates", async () => {
    await expect(
      apiClient.commitEmployeeImport("full_name,email\nAlex Owner,alex@demo.test\n"),
    ).rejects.toBeInstanceOf(ApiError);
  });

  it("previews and commits a clean supplier import", async () => {
    const csv =
      "name,code,approval_status,contact_name,contact_email\nUnique Vendor,UV-1,pending,Pat,pat@uv.test\n";
    const preview = await apiClient.previewSupplierImport(csv);
    expect(preview.valid_count).toBe(1);
    const committed = await apiClient.commitSupplierImport(csv);
    expect(committed.created_count).toBe(1);
  });
});
