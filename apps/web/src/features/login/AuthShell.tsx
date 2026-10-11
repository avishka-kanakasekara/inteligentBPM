import type { ReactNode } from "react";
import { BrandLogo } from "../../components/brand/BrandLogo";

type AuthShellProps = {
  children: ReactNode;
  title: string;
  subtitle: string;
  footer?: ReactNode;
};

export function AuthShell({ children, title, subtitle, footer }: AuthShellProps) {
  return (
    <main className="auth-screen">
      <section className="auth-card" aria-labelledby="auth-title">
        <BrandLogo className="brand-logo brand-logo-auth" />
        <h1 id="auth-title">{title}</h1>
        <p className="auth-subtitle">{subtitle}</p>
        {children}
        {footer ? <div className="auth-footer">{footer}</div> : null}
      </section>
    </main>
  );
}
