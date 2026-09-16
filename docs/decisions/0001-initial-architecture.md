# ADR 0001: Initial Architecture

## Status

Accepted

## Date

2026-09-15

## Context

We are building a production-grade, multi-tenant intelligent business process management platform with four Gemini (Vertex AI) agents, human approvals, and controlled external side effects. The team needs a durable product/technical contract before implementing application code.

Constraints include:

- Multi-tenant data isolation with `organization_id` and RLS
- No LLM direct access to PostgreSQL, email, or purchasing
- Typed tool gateway for all business side effects
- Managed services preferred over self-hosted infrastructure
- **No Docker or container technology** for local development or deployment
- Modular monolith to start, not microservices

## Decision

1. **Modular monolith** on FastAPI with thin routes, application services, and repositories.
2. **React + TypeScript + Vite** frontend; Zod for client validation only.
3. **Supabase** for Auth, PostgreSQL, Storage, and SQL migrations; **pgvector** for embeddings.
4. **SQLAlchemy 2.x** in the backend; Pydantic v2 for API and agent schemas.
5. **Gemini via Vertex AI** using the official Google Gen AI Python SDK; model IDs configured, not hardcoded previews.
6. **Temporal Cloud** for durable orchestration, with a **native mock/test workflow mode** for local development without containers.
7. **Managed Redis** (or local native Redis install) for cache and rate limiting.
8. **SSE** for realtime process status by default.
9. **Outbox/inbox**, idempotency keys, optimistic locking, and append-only audit events as core reliability patterns.
10. **Server-side entitlements** for Pro / Enterprise / Pro Max.
11. **Mock adapters** for email, suppliers, purchasing, and billing until real credentials exist.
12. **Native local development**: Python venv + Node tooling; hosted Supabase dev project.
13. **Managed deployment**: static frontend hosting + managed Python runtime/buildpacks; **no containers**.

## Consequences

### Positive

- Clear security and agent boundaries before coding
- Faster iteration with a monolith and managed services
- Portable contracts for AuthZ, approvals, and tools
- Local DX without Docker complexity

### Negative / trade-offs

- Monolith module discipline must be enforced to avoid spaghetti
- Temporal Cloud dependency (mitigated by mock mode)
- Hosted Supabase required even for local (no default local Postgres path)
- Some platform features (deep isolation) rely on RLS + careful service-role usage rather than network-level service meshes

## Rejected alternatives

| Alternative | Reason rejected |
| --- | --- |
| Container-based local/prod (Docker/K8s) | Explicit project prohibition |
| Microservices from day one | Premature complexity |
| LLM with SQL tools | Violates non-negotiable safety rules |
| Frontend-enforced entitlements/AuthZ | Insecure |
| Natural-language workflow transitions | Brittle; non-deterministic |
| Self-hosted Postgres-only local default | Conflicts with Supabase-as-provider standard |

## References

- `docs/product-requirements.md`
- `docs/system-architecture.md`
- `docs/agent-contracts.md`
- `docs/workflow-state-machine.md`
- `docs/security-model.md`
- `docs/plan-entitlements.md`
- `docs/integration-boundaries.md`
- `docs/api-surface.md`
- `docs/local-development.md`
- `docs/deployment.md`
