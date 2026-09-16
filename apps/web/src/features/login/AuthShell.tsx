import type { ReactNode } from "react";

type AuthShellProps = {
  children: ReactNode;
  title: string;
  subtitle: string;
  footer?: ReactNode;
};

const STAGES = [
  { title: "Discover", desc: "Interview processes and draft executable plans." },
  { title: "Allocate", desc: "Match people, suppliers, and systems to each step." },
  { title: "Approve", desc: "Review risk, policy evidence, and required decisions." },
  { title: "Execute", desc: "Run approved work and capture auditable artifacts." },
];

/**
 * Split-screen light auth composition — brand/workflow left, form right.
 */
export function AuthShell({ children, title, subtitle, footer }: AuthShellProps) {
  return (
    <main className="auth-split">
      <aside className="auth-aside" aria-hidden="false">
        <div className="auth-aside-grid" aria-hidden="true" />
        <div className="auth-aside-inner">
          <span className="brand-mark" aria-hidden="true" />
          <p className="auth-brand-name">Intelligent BPM</p>
          <p className="auth-brand-tag">Discover · Allocate · Approve · Execute</p>
          <p className="auth-aside-copy">
            Operational console for process discovery, allocation, risk-backed approval, and
            controlled execution across finance, procurement, and compliance teams.
          </p>
          <ol className="workflow-stages">
            {STAGES.map((stage, index) => (
              <li key={stage.title}>
                <span className="stage-index">{index + 1}</span>
                <div>
                  <div className="stage-title">{stage.title}</div>
                  <div className="stage-desc">{stage.desc}</div>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </aside>

      <section className="auth-main" aria-labelledby="auth-title">
        <div className="auth-form-plane">
          <h1 id="auth-title">{title}</h1>
          <p className="auth-subtitle">{subtitle}</p>
          {children}
          {footer ? <div className="auth-footer">{footer}</div> : null}
        </div>
        <p className="auth-fineprint">
          Session tokens stay in your browser. Service-role keys are never shipped to the client.
        </p>
      </section>
    </main>
  );
}
