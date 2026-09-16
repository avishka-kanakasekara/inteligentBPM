import { useEffect, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { z } from "zod";
import { useAuth } from "../../providers/AuthProvider";
import { AuthShell } from "./AuthShell";

const schema = z.object({
  email: z.string().email("Enter a valid work email"),
  password: z.string().min(8, "Password must be at least 8 characters"),
});

type FormValues = z.infer<typeof schema>;

export function LoginPage() {
  const { signIn, signOut, isLoading, authError, clearAuthError } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/organizations";
  const confirmed = new URLSearchParams(location.search).get("confirmed") === "1";
  const [showPassword, setShowPassword] = useState(false);

  useEffect(() => {
    if (location.search.includes("logout=true")) {
      void signOut();
    }
  }, [location.search, signOut]);

  useEffect(() => {
    clearAuthError();
  }, [clearAuthError]);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      email: "",
      password: "",
    },
  });

  return (
    <AuthShell
      title="Sign in"
      subtitle="Sign in to allocate resources, review approvals, and execute controlled processes."
      footer={
        <p>
          New here? <Link to="/signup">Create an account</Link>
        </p>
      }
    >
      {confirmed ? (
        <p className="auth-banner" role="status">
          Email confirmed. Sign in to continue.
        </p>
      ) : null}

      <form
        className="auth-form"
        onSubmit={(event) => {
          void handleSubmit(async (values) => {
            try {
              await signIn(values.email, values.password);
              navigate(from, { replace: true });
            } catch {
              // authError surfaced by provider
            }
          })(event);
        }}
        noValidate
      >
        <div className="auth-field">
          <label htmlFor="email">Work email</label>
          <input
            id="email"
            type="email"
            autoComplete="username"
            placeholder="you@company.com"
            aria-invalid={Boolean(errors.email)}
            aria-describedby={errors.email ? "email-error" : undefined}
            {...register("email")}
          />
          {errors.email ? (
            <p id="email-error" className="field-error" role="alert">
              {errors.email.message}
            </p>
          ) : null}
        </div>

        <div className="auth-field">
          <label htmlFor="password">Password</label>
          <div className="password-field">
            <input
              id="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              placeholder="At least 8 characters"
              aria-invalid={Boolean(errors.password)}
              aria-describedby={errors.password ? "password-error" : undefined}
              {...register("password")}
            />
            <button
              type="button"
              className="password-toggle"
              onClick={() => setShowPassword((value) => !value)}
              aria-pressed={showPassword}
            >
              {showPassword ? "Hide" : "Show"}
            </button>
          </div>
          {errors.password ? (
            <p id="password-error" className="field-error" role="alert">
              {errors.password.message}
            </p>
          ) : null}
        </div>

        {authError ? (
          <p className="field-error" role="alert">
            {authError}
          </p>
        ) : null}

        <button type="submit" className="auth-submit" disabled={isLoading}>
          {isLoading ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </AuthShell>
  );
}
