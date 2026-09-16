# Product Requirements

## Purpose

This document defines the product contract for a multi-tenant intelligent business process management (BPM) platform. The platform helps organizations discover processes, allocate resources, assess risk and compliance, obtain human approvals, and execute controlled business actions through typed tool gateways—never by giving an LLM direct access to databases, email, purchasing, or other side-effecting systems.

This phase produces product and technical contracts only. Application implementation is out of scope until a later phase.

## Non-negotiable infrastructure constraint

**Docker and all container technology are not used.** The platform must not introduce Dockerfiles, Compose files, container images, Kubernetes manifests, Helm charts, container registries, or container-based local/production workflows. Local development uses Python virtual environments, Node.js package managers, a hosted Supabase project, managed Redis (or locally installed Redis), and Temporal Cloud or a native workflow mock/test mode.

## Product vision

Enable companies to turn informal process intent (chat + documents) into versioned, auditable, approval-gated execution plans that allocate real company context (people, departments, suppliers, policies) and only perform external actions through a controlled tool gateway.

## Company instance / organization model

- Each customer company is an **organization** (tenant).
- Users authenticate once (Supabase Auth) and may belong to **multiple organizations**.
- Every tenant-owned row is scoped by `organization_id`.
- The active organization for a request is derived from **server-side membership and session context**, never trusted from a client-supplied `organization_id` alone.
- Organization configuration includes: display name, plan tier, feature entitlements, integration settings, notification preferences, and policy defaults.

## Personas

| Persona | Description |
| --- | --- |
| Org Owner | Creates/configures organization; manages billing plan and integrations |
| Admin | Manages directories, roles, memberships, suppliers, policies |
| Manager | Approves processes in scope; allocates/reviews resources |
| Employee | Discovers processes, uploads documents, participates as assigned resource |
| Compliance Officer | Reviews risk/policy findings; may be required approver |
| Auditor (read-only) | Views audit trails and process history without mutation rights |
| Platform Operator | Operates staging/production infra; no tenant data access by default |

## User roles and permissions (product-level)

Roles are organization-scoped. Global platform roles (if any) are separate and never implied by org membership.

| Capability | Owner | Admin | Manager | Employee | Compliance | Auditor |
| --- | --- | --- | --- | --- | --- | --- |
| Create organization | Yes (self) | — | — | — | — | — |
| Configure org / plan | Yes | Limited | No | No | No | No |
| Manage members & roles | Yes | Yes | No | No | No | No |
| Manage departments | Yes | Yes | Own dept (limited) | No | No | No |
| Manage suppliers | Yes | Yes | Limited | View | View | View |
| Manage policies/docs | Yes | Yes | View | View | Yes | View |
| Start process discovery | Yes | Yes | Yes | Yes | Yes | No |
| Upload process documents | Yes | Yes | Yes | Yes | Yes | No |
| Request/approve approvals | Approve all | Approve scoped | Approve scoped | Request only | Approve compliance | No |
| Execute approved actions | Yes | Yes | Scoped | Assigned only | No | No |
| View audit logs | Yes | Yes | Scoped | Own actions | Yes | Yes |
| Configure integrations | Yes | Yes | No | No | No | No |
| View usage metering | Yes | Yes | No | No | No | View |

Exact permission codes and enforcement live in `docs/security-model.md` and `docs/api-surface.md`. The frontend must never be the source of truth for authorization.

## Organization membership rules

1. A user may hold memberships in multiple organizations with different roles per org.
2. Membership requires an explicit invite/accept or owner bootstrap at org creation.
3. Suspended or removed membership immediately revokes access to that org’s data.
4. Role changes take effect on subsequent authorization checks; in-flight workflows must re-check authorization before side effects.
5. Leaving an org does not delete historical audit events; attribution remains.
6. Service accounts / integration principals (if introduced later) must be org-scoped and separately audited.

## Core product capabilities

### Organization and directory

- Organization creation and configuration
- Employee and manager directory
- Departments and roles
- Supplier and supplier-contact directory

### Knowledge and compliance

- Company policies and compliance documents
- Document upload, processing, versioning, and retrieval for agent context
- Vector search over approved org knowledge (pgvector), tenant-scoped

### Intelligent process lifecycle

1. **Process discovery chat** — Agent 1 clarifies intent and produces a versioned execution plan
2. **Resource & company context allocation** — Agent 2 binds people, departments, suppliers, and documents
3. **Risk, policy, and compliance analysis** — Agent 3 evaluates policy fit and residual risk
4. **Human approvals** — immutable snapshots; invalidation on material change
5. **Controlled process execution** — Agent 4 proposes tool calls; gateway executes only after validation/approval

### Commercial and operational

- Email sending (via tool gateway)
- Supplier quotation collection and comparison
- Purchase order drafts (no silent purchasing)
- Audit logs for every material decision and side effect
- Usage metering
- Plans: **Pro**, **Enterprise**, **Pro Max**
- Integration configuration
- Notifications
- Real-time process status updates (SSE by default)

## Four intelligent agents (product summary)

| Agent | Responsibility |
| --- | --- |
| Agent 1 — Process Discovery & Execution Planning | Conversational discovery; structured, versioned process plan |
| Agent 2 — Resource & Company Context Allocation | Map plan steps to org people, departments, suppliers, and docs |
| Agent 3 — Risk, Policy & Compliance Analysis | Policy/compliance scoring; blockers; required approvals |
| Agent 4 — Controlled Process Execution | Propose gateway tool invocations; never execute side effects directly |

Agents return **structured JSON** validated by Pydantic. Natural language is for user communication only—not for workflow state transitions. Detailed contracts: `docs/agent-contracts.md`.

## Process outcomes users expect

- Versioned process plans with clear change history
- Allocated resources with rationale summaries (not hidden chain-of-thought)
- Risk decisions with evidence references to policy/document IDs
- Approval packages containing immutable snapshots of plan + allocation + risk
- Execution that is idempotent, approvable, and fully audited
- Transparent failure, retry, and compensation states

## Explicit non-goals (this product phase and platform principles)

- LLM direct SQL or database access
- LLM direct email send or purchase without gateway + policy
- Docker/container-based packaging or deployment
- Inventing missing company data
- Silently continuing after policy violations
- Storing full chain-of-thought or secrets in logs
- Hardcoding preview Gemini model IDs
- Trusting client-provided authorization, plan limits, or approval status

## Success criteria (contract level)

- A new organization can be created and configured without engineering intervention (once app exists).
- An employee can discover a process, upload supporting docs, receive a plan, allocation, and risk package.
- Managers/compliance can approve or reject with auditability.
- Approved execution performs only gateway-mediated tools with idempotency keys.
- Tenant A cannot read or mutate Tenant B data at API or database (RLS) layers.
- Plan entitlements are enforced server-side.
- All environments (local, staging, production) run without containers.

## Related documents

- `docs/system-architecture.md`
- `docs/agent-contracts.md`
- `docs/workflow-state-machine.md`
- `docs/security-model.md`
- `docs/plan-entitlements.md`
- `docs/integration-boundaries.md`
- `docs/api-surface.md`
- `docs/local-development.md`
- `docs/deployment.md`
- `docs/decisions/0001-initial-architecture.md`
