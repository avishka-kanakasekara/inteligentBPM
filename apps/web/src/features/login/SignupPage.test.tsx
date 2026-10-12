import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { LoginPage } from "./LoginPage";
import { SignupPage } from "./SignupPage";

const signUp = vi.hoisted(() => vi.fn());
const signIn = vi.hoisted(() => vi.fn());

vi.mock("../../providers/AuthProvider", () => ({
  useAuth: () => ({
    signUp,
    signIn,
    signOut: vi.fn(),
    isLoading: false,
    authError: null,
    clearAuthError: vi.fn(),
  }),
}));

describe("signup confirmation messaging", () => {
  it("does not tell the user the email is confirmed before they use the link", async () => {
    const user = userEvent.setup();
    signUp.mockResolvedValue({
      kind: "confirm_email",
      email: "friend@example.com",
      message: "Account created. Check your email to confirm, then sign in.",
    });
    render(
      <MemoryRouter>
        <SignupPage />
      </MemoryRouter>,
    );
    await user.type(screen.getByLabelText(/full name/i), "Friend Example");
    await user.type(screen.getByLabelText(/work email/i), "friend@example.com");
    await user.type(screen.getByLabelText(/^password$/i), "Signup9login");
    await user.type(screen.getByLabelText(/confirm password/i), "Signup9login");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(signUp).toHaveBeenCalledWith({
      email: "friend@example.com",
      password: "Signup9login",
      fullName: "Friend Example",
    });
    const signInLink = await screen.findByRole("link", { name: /go to sign in/i });
    expect(signInLink).toHaveAttribute("href", "/login?confirm=1");
    expect(screen.queryByText(/email confirmed/i)).not.toBeInTheDocument();
  });

  it("keeps the login page from claiming confirmation just because signup finished", () => {
    render(
      <MemoryRouter initialEntries={["/login?confirmed=1"]}>
        <LoginPage />
      </MemoryRouter>,
    );
    expect(screen.queryByText(/email confirmed/i)).not.toBeInTheDocument();
  });

  it("asks the user to confirm before signing in", () => {
    render(
      <MemoryRouter initialEntries={["/login?confirm=1"]}>
        <LoginPage />
      </MemoryRouter>,
    );
    expect(
      screen.getByText(/confirm your email from the link we sent, then sign in with the same password/i),
    ).toBeInTheDocument();
  });
});
