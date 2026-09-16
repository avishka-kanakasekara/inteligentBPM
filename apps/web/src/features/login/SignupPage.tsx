import { useEffect, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";
import { z } from "zod";
import { useAuth } from "../../providers/AuthProvider";
import { AuthShell } from "./AuthShell";

const schema = z
  .object({
    fullName: z.string().min(2, "Enter your full name"),
    email: z.string().email("Enter a valid work email"),
    password: z
      .string()
      .min(8, "Use at least 8 characters")
      .regex(/[A-Za-z]/, "Include a letter")
      .regex(/[0-9]/, "Include a number"),
    confirmPassword: z.string().min(8, "Confirm your password"),
  })
  .refine((values) => values.password === values.confirmPassword, {
    message: "Passwords do not match",
    path: ["confirmPassword"],
  });

type FormValues = z.infer<typeof schema>;

export function SignupPage() {
  const { signUp, isLoading, authError, clearAuthError } = useAuth();
  const navigate = useNavigate();
  const [confirmMessage, setConfirmMessage] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);

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
      fullName: "",
      email: "",
      password: "",
      confirmPassword: "",
    },
  });

  if (confirmMessage) {
    return (
      <AuthShell
        title="Check your inbox"
        subtitle="Confirm your email, then sign in to choose or create an organization."
        footer={
          <p>
            Ready? <Link to="/login?confirmed=1">Sign in</Link>
          </p>
        }
      >
        <p className="auth-banner" role="status">
          {confirmMessage}
        </p>
        <Link className="auth-submit auth-link-btn" to="/login?confirmed=1">
          Go to sign in
        </Link>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Create account"
      subtitle="Join Intelligent BPM to discover processes, allocate resources, and execute with approval gates."
      footer={
        <p>
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      }
    >
      <form
        className="auth-form"
        onSubmit={(event) => {
          void handleSubmit(async (values) => {
            try {
              const outcome = await signUp({
                email: values.email,
                password: values.password,
                fullName: values.fullName,
              });
              if (outcome.kind === "confirm_email") {
                setConfirmMessage(outcome.message);
                return;
              }
              navigate("/organizations", { replace: true });
            } catch {
              // authError surfaced by provider
            }
          })(event);
        }}
        noValidate
      >
        <div className="auth-field">
          <label htmlFor="fullName">Full name</label>
          <input
            id="fullName"
            type="text"
            autoComplete="name"
            placeholder="Alex Owner"
            aria-invalid={Boolean(errors.fullName)}
            {...register("fullName")}
          />
          {errors.fullName ? (
            <p className="field-error" role="alert">
              {errors.fullName.message}
            </p>
          ) : null}
        </div>

        <div className="auth-field">
          <label htmlFor="email">Work email</label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            placeholder="you@company.com"
            aria-invalid={Boolean(errors.email)}
            {...register("email")}
          />
          {errors.email ? (
            <p className="field-error" role="alert">
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
              autoComplete="new-password"
              placeholder="8+ characters, letter and number"
              aria-invalid={Boolean(errors.password)}
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
            <p className="field-error" role="alert">
              {errors.password.message}
            </p>
          ) : null}
        </div>

        <div className="auth-field">
          <label htmlFor="confirmPassword">Confirm password</label>
          <input
            id="confirmPassword"
            type={showPassword ? "text" : "password"}
            autoComplete="new-password"
            placeholder="Repeat password"
            aria-invalid={Boolean(errors.confirmPassword)}
            {...register("confirmPassword")}
          />
          {errors.confirmPassword ? (
            <p className="field-error" role="alert">
              {errors.confirmPassword.message}
            </p>
          ) : null}
        </div>

        {authError ? (
          <p className="field-error" role="alert">
            {authError}
          </p>
        ) : null}

        <button type="submit" className="auth-submit" disabled={isLoading}>
          {isLoading ? "Creating account…" : "Create account"}
        </button>
      </form>
    </AuthShell>
  );
}
