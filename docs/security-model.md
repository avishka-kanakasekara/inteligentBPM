# Security Model

## Purpose

Security and tenant-isolation contract for the platform. Authorization, entitlements, and approval status are **server-enforced**. The frontend must never be treated as authoritative for those decisions.

**Docker and container technology are not used.** Security posture does not depend on container isolation; it depends on AuthN/AuthZ, RLS, secrets management, and gateway controls on managed runtimes.

## Threat assumptions (summary)

- Multi-tenant SaaS with hostile tenants and compromised end-user browsers.
- Prompt injection via uploaded documents and external tool text.
- Confused-deputy risk if agents or tools are given broad credentials.
- Secret leakage via logs, SSE, or client bundles.

## Authentication

- **Supabase Auth** for end users (email/OAuth as configured per environment).
- Backend validates JWTs / session tokens on every API request.
- Browser receives only the Supabase **anon/public** key and user session—**never** the service role key or other secrets.
- Service role key is restricted to trusted backend processes and migration/admin tooling.

## Organization context and membership

1. Resolve `user_id` from the verified session.
2. Resolve **active organization** from server-side membership (header/cookie as hint only if cross-checked).
3. **Do not trust** client-supplied `organization_id` without membership verification.
4. Load role(s) and permissions for `(user_id, organization_id)`.
5. Reject requests if membership is missing, suspended, or role lacks permission.

Users may belong to multiple organizations; permissions are always evaluated in the active org context.

## Authorization model

### Roles (org-scoped)

`owner` | `admin` | `manager` | `employee` | `compliance` | `auditor`

### Permission codes (illustrative stable set)

- `org.configure`
- `members.manage`
- `directory.manage` / `directory.read`
- `suppliers.manage` / `suppliers.read`
- `policies.manage` / `policies.read`
- `documents.upload` / `documents.read`
- `processes.create` / `processes.read` / `processes.cancel`
- `approvals.decide`
- `execution.run`
- `integrations.configure`
- `audit.read`
- `usage.read`
- `notifications.manage`

Services check permission codes; routes stay thin.

### Rules

- Frontend may hide UI, but API re-checks every mutation and sensitive read.
- Workflow activities re-check AuthZ before side effects (membership may have changed).
- Agent proposals do not grant authority; the gateway does.

## Tenant isolation requirements

| Layer | Control |
| --- | --- |
| API | Org membership + permission checks on every handler/service |
| Repository | Mandatory `organization_id` predicate from server context |
| Database | **RLS enabled on every exposed tenant table** |
| Storage | Path/bucket policies scoped by org; signed URLs time-limited |
| Vectors | Embeddings rows include `organization_id`; queries filter by org |
| Cache | Redis keys prefixed by org (and env); no cross-tenant key reuse |
| SSE | Subscriptions authorized per process ACL + membership |
| Logs | Include org ID; exclude secrets and full sensitive document bodies |
| Metering | Counters per org; no cross-org aggregation in tenant APIs |

Cross-tenant access is a **P0** defect. Tests must include database security / RLS tests.

## Row Level Security

- Enable RLS for all tenant tables exposed to Supabase clients or shared DB roles.
- Policies must enforce `organization_id` membership (via JWT claims and/or secure policy helpers).
- Backend using service role must still apply application-level filters; service role bypass of RLS is a privileged path requiring extreme care and audit.
- Prefer least-privilege DB roles for runtime where feasible.

## Tool gateway security

1. Validate caller identity, org, permissions, and entitlements.
2. Validate input against Pydantic schemas; reject unknown fields as configured.
3. Enforce idempotency keys for mutating tools.
4. Bind high-risk tools to an **approval snapshot ID** that is still `approved` and not `invalidated`.
5. Adapters hold provider secrets; agents never see them.
6. Treat tool responses as untrusted input to subsequent LLM steps.
7. Audit every proposal, denial, and execution result.

## Document and prompt-injection defenses

- Size/type limits; optional malware scanning hooks.
- Quarantine on suspicious content patterns as configured.
- Untrusted content delimited in prompts; system instructions forbid obeying document-origin tool/DB directives.
- Do not place secrets in prompts.
- Retrieval returns only org-scoped chunks.

## Secrets management

- Local: `.env` (never committed); use `.env.example` placeholders only.
- Staging/production: cloud/managed secret storage or host secret variables.
- No fake production credentials in the repository.
- Rotate keys per environment; separate Supabase projects per env.

## Logging and audit

### Audit requirements

Append-only audit events for:

- AuthZ denials of sensitive operations (as appropriate)
- Process state transitions
- Plan version creation
- Approval request/decision/invalidation
- Tool proposals, denials, executions
- Integration configuration changes
- Membership/role changes
- Entitlement/plan changes

Each event: `event_id`, `organization_id`, `actor_user_id` (or system), `action`, `resource_type`, `resource_id`, `correlation_id`, `trace_id`, `timestamp`, `payload` (redacted), `integrity` metadata as implemented.

### Log redaction

Never log: access tokens, service keys, passwords, full PAN-like data, or full sensitive document contents. Prefer hashes and IDs.

## Abuse and rate limiting

- Redis-backed rate limits per user/org/IP for auth, chat, upload, and tool-heavy endpoints.
- Plan quotas enforced server-side (see `docs/plan-entitlements.md`).

## Error responses

Structured errors with stable codes (e.g., `AUTH_FORBIDDEN`, `TENANT_MISMATCH`, `APPROVAL_INVALIDATED`, `ENTITLEMENT_DENIED`). Include `correlation_id`; do not leak stack traces or secrets to clients.

## Testing obligations

- Unit tests for permission matrix critical paths
- Contract tests for AuthZ on API surface
- Database security tests for RLS isolation
- Prompt-injection regression fixtures for document context assembly
