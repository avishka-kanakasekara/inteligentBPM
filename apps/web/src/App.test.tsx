import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, beforeEach } from "vitest";
import { App } from "./App";
import { ProcessStatusCard } from "./components/process/ProcessStatusCard";
import { ApprovalBadge, ProcessStatusBadge, RiskBadge } from "./components/process/StatusBadges";
import { EmptyState } from "./components/ui/EmptyState";
import { LoadingState } from "./components/ui/LoadingState";
import { ApiError } from "./lib/apiClient";
import { mockApi } from "./lib/mockApi";
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

async function signInAs(user: ReturnType<typeof userEvent.setup>, email = "alex@demo.test") {
  await user.type(screen.getByLabelText(/work email/i), email);
  await user.type(screen.getByLabelText(/^password$/i), "password123");
  await user.click(screen.getByRole("button", { name: /^sign in$/i }));
}

beforeEach(() => {
  sessionStore.clear();
  localStorage.clear();
});

describe("route protection", () => {
  it("redirects unauthenticated users to login", async () => {
    renderApp("/dashboard");
    expect(await screen.findByRole("heading", { name: /sign in/i })).toBeInTheDocument();
  });
});

describe("organization switching", () => {
  it("lets an authenticated user switch organizations", async () => {
    const user = userEvent.setup();
    renderApp("/login");

    await signInAs(user);
    expect(await screen.findByRole("heading", { name: /select organization/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /acme enterprise/i }));
    expect(await screen.findByRole("heading", { name: /dashboard/i })).toBeInTheDocument();
    expect(screen.getAllByText(/acme enterprise/i).length).toBeGreaterThan(0);
  });
});

describe("permission-based visibility", () => {
  it("hides audit nav for manager role after switching to Acme", async () => {
    const user = userEvent.setup();
    renderApp("/login");
    await signInAs(user);
    await user.click(await screen.findByRole("button", { name: /acme enterprise/i }));
    expect(await screen.findByRole("heading", { name: /dashboard/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^audit$/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^approvals$/i })).toBeInTheDocument();
  });
});

describe("API error handling", () => {
  it("surfaces ApiError codes from mock failures", async () => {
    await expect(mockApi.request("/boom")).rejects.toBeInstanceOf(ApiError);
    try {
      await mockApi.request("/boom");
    } catch (error) {
      expect(error).toMatchObject({ code: "INTERNAL_ERROR", status: 500 });
    }
  });
});

describe("process and approval rendering", () => {
  it("renders process status, risk, approval, and evidence fields", () => {
    const process = mockApi.processes[0];
    render(
      <AppProviders>
        <ProcessStatusCard process={process} />
      </AppProviders>,
    );
    expect(screen.getByText(process.name)).toBeInTheDocument();
    expect(screen.getByText(/awaiting approval/i)).toBeInTheDocument();
    expect(screen.getByText(/risk: medium/i)).toBeInTheDocument();
    expect(screen.getByText(/preferred supplier sla/i)).toBeInTheDocument();
    expect(screen.getByText(/procurement approval policy/i)).toBeInTheDocument();
  });

  it("renders approval and risk badges", () => {
    render(
      <>
        <ProcessStatusBadge status="executing" />
        <RiskBadge level="high" />
        <ApprovalBadge status="pending" />
      </>,
    );
    expect(screen.getByText(/executing/i)).toBeInTheDocument();
    expect(screen.getByText(/risk: high/i)).toBeInTheDocument();
    expect(screen.getByText(/approval: pending/i)).toBeInTheDocument();
  });
});

describe("loading and empty states", () => {
  it("renders loading and empty messaging", () => {
    render(
      <>
        <LoadingState label="Fetching processes…" />
        <EmptyState title="No processes yet" description="Start discovery to begin." />
      </>,
    );
    expect(screen.getByText(/fetching processes/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /no processes yet/i })).toBeInTheDocument();
  });
});

describe("approvals page", () => {
  it("shows approval center content when entitled", async () => {
    const user = userEvent.setup();
    renderApp("/login");
    await signInAs(user);
    await user.click(await screen.findByRole("button", { name: /demo organization/i }));
    await user.click(await screen.findByRole("link", { name: /^approvals$/i }));
    expect(await screen.findByRole("heading", { name: /risk and approval center/i })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getAllByText(/laptop procurement/i).length).toBeGreaterThan(0);
    });
  });
});
