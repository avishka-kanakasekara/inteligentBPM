# API Surface

## Purpose

Contract for the HTTP/SSE API of the modular FastAPI backend. Routes are thin; AuthZ, entitlements, and tenant resolution occur in application services. This document is a **surface contract**, not a generated OpenAPI dump.

**Docker and container technology are not used** to host the API.

## Cross-cutting conventions

| Concern | Contract |
| --- | --- |
| Base path | `/api/v1` |
| Auth | Bearer session/JWT from Supabase Auth |
| Active org | Server-validated membership (e.g., `X-Organization-Id` hint + membership check) |
| Correlation | Accept/propagate `X-Correlation-Id`; generate if missing |
| Trace | Internal `trace_id` attached to logs/workflows |
| Errors | JSON `{ "error": { "code", "message", "details?", "correlation_id" } }` |
| Validation | Pydantic request bodies; stable validation error code |
| Idempotency | `Idempotency-Key` header on mutating side-effect endpoints |
| Listing | Cursor/limit pagination; org-scoped |

Clients **must not** send service-role keys. `organization_id` in bodies is ignored unless it matches server context (prefer omitting).

## Identity and tenancy

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/me` | Current user profile |
| GET | `/me/organizations` | Memberships and roles |
| POST | `/organizations` | Create organization (caller becomes owner) |
| GET | `/organizations/current` | Active org config |
| PATCH | `/organizations/current` | Update org config (authorized) |
| POST | `/organizations/current/invites` | Invite member |
| POST | `/organizations/invites/{token}/accept` | Accept invite |
| PATCH | `/organizations/current/members/{user_id}` | Change role / suspend |

## Directory

| Method | Path | Purpose |
| --- | --- | --- |
| GET/POST | `/employees` | List/create employees |
| GET/PATCH | `/employees/{id}` | Read/update |
| GET/POST | `/departments` | List/create departments |
| GET/PATCH | `/departments/{id}` | Read/update |
| GET | `/roles` | List org roles / permission maps |

## Suppliers

| Method | Path | Purpose |
| --- | --- | --- |
| GET/POST | `/suppliers` | List/create suppliers |
| GET/PATCH | `/suppliers/{id}` | Read/update |
| GET/POST | `/suppliers/{id}/contacts` | Supplier contacts |

## Policies and documents

| Method | Path | Purpose |
| --- | --- | --- |
| GET/POST | `/policies` | Policy metadata |
| POST | `/documents` | Initiate upload (returns storage instructions / confirmed metadata) |
| GET | `/documents/{id}` | Metadata + processing status |
| POST | `/documents/{id}/reprocess` | Re-queue ingestion |
| GET | `/documents/search` | Tenant-scoped semantic/keyword search |

## Processes and agents

| Method | Path | Purpose |
| --- | --- | --- |
| GET/POST | `/processes` | List/create process |
| GET | `/processes/{id}` | Process detail + status |
| POST | `/processes/{id}/messages` | Discovery chat message |
| GET | `/processes/{id}/plan` | Current plan version |
| GET | `/processes/{id}/plan/versions` | Version history |
| POST | `/processes/{id}/allocate` | Request Agent 2 |
| GET | `/processes/{id}/allocation` | Current allocation |
| POST | `/processes/{id}/analyze-risk` | Request Agent 3 |
| GET | `/processes/{id}/risk` | Current risk result |
| POST | `/processes/{id}/cancel` | Cancel process |

Orchestration may also advance automatically via Temporal; these endpoints expose explicit triggers where product requires them.

## Approvals

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/processes/{id}/approvals` | Create approval package from current snapshots |
| GET | `/processes/{id}/approvals/current` | Current package + state |
| POST | `/approvals/{id}/decide` | Approve/reject (optimistic lock version required) |
| GET | `/approvals` | Inbox for current user |

## Execution

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/processes/{id}/execute` | Start execution against approved snapshot |
| GET | `/processes/{id}/execution` | Execution status and tool call history |
| POST | `/processes/{id}/execution/resume` | Resume after checkpoint/block |

## Commercial artifacts (gateway-backed)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/processes/{id}/quotations` | Collected quotations |
| POST | `/processes/{id}/quotations/compare` | Comparison view (deterministic + optional agent assist) |
| GET/POST | `/processes/{id}/purchase-orders` | List/create PO drafts via gateway |
| POST | `/purchase-orders/{id}/submit` | Controlled submit if entitled + approved |

## Integrations, metering, audit, notifications

| Method | Path | Purpose |
| --- | --- | --- |
| GET/PATCH | `/integrations` | Org integration settings (secrets write-only) |
| GET | `/usage` | Metering counters for current period |
| GET | `/entitlements` | Resolved feature/quota snapshot |
| GET | `/audit-events` | Filtered audit log |
| GET | `/notifications` | List notifications |
| POST | `/notifications/{id}/read` | Mark read |

## Realtime (SSE)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/processes/{id}/events` | SSE stream of process/agent/tool status |

SSE requires the same AuthZ as process read. Event payloads exclude secrets and full sensitive documents.

## Health

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/healthz` | Liveness |
| GET | `/readyz` | Readiness (DB/Redis configured checks) |

## Stable error codes (non-exhaustive)

`AUTH_UNAUTHORIZED`, `AUTH_FORBIDDEN`, `TENANT_MISMATCH`, `VALIDATION_ERROR`, `NOT_FOUND`, `PROCESS_VERSION_CONFLICT`, `APPROVAL_VERSION_CONFLICT`, `APPROVAL_INVALIDATED`, `ENTITLEMENT_DENIED`, `QUOTA_EXCEEDED`, `POLICY_BLOCKED`, `TOOL_DENIED`, `TOOL_FAILED`, `IDEMPOTENCY_CONFLICT`, `RATE_LIMITED`, `INTERNAL_ERROR`

## Frontend trust boundary

- Zod validates UX shapes only.
- Authorization, plan limits, and approval status are always re-fetched/enforced from the API.
- Never embed service keys in the Vite bundle.
