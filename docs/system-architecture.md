# System Architecture

## Purpose

Technical architecture contract for the multi-tenant intelligent BPM platform: modular monolith, managed services, typed agents, durable workflows, and a mandatory tool gateway for all side effects.

**Docker and container technology are not used** anywhere in local development, CI, or deployment.

## High-level shape

```
┌─────────────────────────────────────────────────────────────────┐
│  React + TypeScript + Vite (managed static hosting)             │
│  Zod validation · SSE client · Supabase Auth (anon key only)    │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTPS / SSE
┌────────────────────────────▼────────────────────────────────────┐
│  FastAPI modular monolith (managed Python runtime / buildpacks) │
│  API routes (thin) → Application services → Repositories        │
│  AuthZ · Entitlements · Correlation/Trace IDs · Pydantic v2     │
└───┬──────────────┬──────────────┬──────────────┬────────────────┘
    │              │              │              │
    ▼              ▼              ▼              ▼
 Supabase       Redis          Temporal       Vertex AI
 PostgreSQL+    cache/         Cloud or       Gemini via
 Auth+Storage   rate limit     mock mode      Google Gen AI SDK
 pgvector       (managed)      (managed)      (adapter)
    │
    ▼
 Tool Gateway → Adapters (email, suppliers, purchasing, billing)
                mocks until real credentials configured
```

## Architectural style

- **Modular monolith** initially: single deployable FastAPI app with clear internal modules.
- **Thin API routes**; business logic in **application services**; persistence in **repositories**.
- **Provider-agnostic ports** with adapters for Supabase, Redis, Temporal, Vertex AI, email, purchasing, billing.
- **Typed domain events** and **typed agent messages**.
- **Outbox/inbox** (or equivalent durable event mechanism) for reliable side effects and cross-module messaging.
- Agents remain **independent of infrastructure providers**; they consume ports and return Pydantic-validated structures.

## Logical modules

| Module | Responsibility |
| --- | --- |
| `identity` | Users, sessions, org membership resolution |
| `tenancy` | Organizations, invites, active-org context |
| `directory` | Employees, managers, departments, roles |
| `suppliers` | Supplier and contact directory |
| `policies` | Policy/compliance document registry |
| `documents` | Upload, virus/type checks, extraction, embeddings |
| `processes` | Process instances, plan versions, status |
| `agents` | Agent orchestration interfaces (1–4) |
| `approvals` | Snapshots, approval state, invalidation |
| `execution` | Execution runs bound to approved snapshots |
| `tools` | Tool gateway, schemas, idempotency, mocks |
| `audit` | Append-only audit events |
| `metering` | Usage counters and plan checks |
| `entitlements` | Server-side feature flags by plan |
| `integrations` | Per-org integration configuration |
| `notifications` | In-app/email notification fan-out |
| `realtime` | SSE streams for process status |
| `workflows` | Temporal workflows/activities or mock runner |

## Data architecture

### Primary store

- **PostgreSQL via Supabase** for transactional data.
- **SQLAlchemy 2.x** in the backend application.
- **Supabase SQL migrations** as the migration source of truth.
- **pgvector** for tenant-scoped embeddings.
- **Row Level Security (RLS)** on every exposed tenant table.

### Tenant key

Every tenant-owned row includes `organization_id`. Repositories always filter by the **server-resolved** organization. Client-supplied org IDs are never authoritative.

### Supporting stores

| Store | Use |
| --- | --- |
| Supabase Storage | Uploaded documents (tenant-partitioned paths/buckets policies) |
| Redis | Cache, rate limiting, short-lived locks/tokens |
| Temporal Cloud | Durable process orchestration (or native mock mode locally) |

## LLM and agent runtime

- LLM: **Gemini through Vertex AI** using the official **Google Gen AI Python SDK**.
- Do **not** hardcode preview Gemini model IDs; configure stable model names via environment.
- Agents emit **structured JSON** validated by Pydantic models.
- Preserve official Gemini **tool-call history** required by the selected model/SDK.
- Store **concise reasoning summaries**, evidence references, decisions, and structured outputs only—**no hidden chain-of-thought** storage.
- Uploaded documents and external tool responses are **untrusted**; defend against **prompt injection**.
- **LLMs must not** access PostgreSQL, send email, or purchase products directly.

## Tool gateway

All external side effects pass through a typed tool gateway that enforces:

1. Tenant scope
2. Authorization
3. Input schema (Pydantic)
4. Idempotency keys
5. Approval requirements
6. Plan entitlements / rate limits
7. Audit logging

See `docs/integration-boundaries.md` and `docs/agent-contracts.md`.

## Workflow orchestration

- Prefer **Temporal Cloud** in staging/production.
- Local/dev may use Temporal Cloud (dev namespace) **or** a **native workflow mock/test mode** (in-process or worker without containers).
- Workflow state transitions are driven by **typed events and validated structures**, not natural-language LLM output.
- Optimistic locking on process plan versions and approvals.
- Immutable snapshots of plan + allocation + risk at approval request time; invalidate approvals when those change.

## Realtime

- Default: **Server-Sent Events (SSE)** for process status and agent progress.
- WebSockets only if a later requirement proves SSE insufficient.

## Security and tenancy (architecture hooks)

- API-layer AuthZ + DB-layer RLS.
- Never expose Supabase service/secret keys to the browser.
- Correlation ID and trace ID on every request and workflow run.
- Structured errors with stable error codes.
- Secrets in cloud/managed secret storage—never committed.

Details: `docs/security-model.md`.

## Failure, retry, and durability

| Concern | Approach |
| --- | --- |
| API transient faults | Idempotent handlers where needed; standard HTTP error codes |
| Workflow activities | Temporal retries with bounded backoff; poison-message quarantine |
| External tools | Idempotency keys; safe retries; no duplicate purchases/emails |
| Outbox | Publish after commit; inbox consumers dedupe by event ID |
| Agent failures | Persist failure reason; allow resume from last durable checkpoint |
| Policy violations | Halt progression; require human resolution; audit |

## Environments

| Environment | Database | Frontend | Backend | Workflow | Redis |
| --- | --- | --- | --- | --- | --- |
| Local | Hosted Supabase **dev** project | Vite dev server | Uvicorn in venv | Temporal Cloud dev **or** mock mode | Managed or local Redis install |
| Staging | Supabase **staging** project | Managed static hosting | Managed Python hosting | Temporal Cloud staging | Managed Redis |
| Production | Supabase **production** project | Managed static hosting | Managed Python hosting | Temporal Cloud prod | Managed Redis |

Do **not** assume a local PostgreSQL instance when Supabase is the provider. Use **environment-specific Supabase projects**.

## Explicit exclusions

- No Dockerfiles, Compose, K8s, Helm, or container registries.
- No LLM→DB or LLM→email/purchase bypass of the gateway.
- No frontend-enforced authorization or entitlements.

## Related ADRs

- `docs/decisions/0001-initial-architecture.md`
