# Workflow State Machine

## Purpose

Defines process lifecycle states, human approval states, document ingestion lifecycle, failure/retry behavior, and transition rules. Transitions are driven by **typed events and validated structures**, never by interpreting natural-language LLM prose.

**Docker and container technology are not used** for workflow workers. Workers run as native Python processes against Temporal Cloud or a native mock mode.

## Process lifecycle states

Primary `process.status` values:

| State | Meaning |
| --- | --- |
| `draft` | Process created; discovery not started or incomplete |
| `discovering` | Agent 1 active |
| `plan_ready` | Validated plan version available |
| `allocating` | Agent 2 active |
| `allocated` | Resource allocation validated |
| `analyzing_risk` | Agent 3 active |
| `risk_complete` | Risk result validated |
| `awaiting_approval` | Approval package submitted to humans |
| `approved` | All required approvals granted for current snapshot |
| `rejected` | Approval denied; may revise |
| `executing` | Agent 4 + gateway executing approved work |
| `blocked` | Policy/data/integration blocker needing human resolution |
| `failed` | Unrecoverable or exhausted retries |
| `completed` | Successful terminal state |
| `cancelled` | Explicit user/admin cancellation |

### Allowed transitions (summary)

```
draft → discovering → plan_ready → allocating → allocated → analyzing_risk → risk_complete
  → awaiting_approval → approved → executing → completed
                 ↘ rejected → discovering | plan_ready | cancelled
approved → awaiting_approval (on ApprovalInvalidated + re-submit)
any non-terminal → blocked | cancelled | failed
blocked → prior durable state after resolution (workflow-defined)
executing → blocked | failed | completed | awaiting_approval (mid-exec checkpoint)
```

Illegal transitions return stable error codes and are audited.

## Plan versioning

- Plans are **append-only versions** (`plan_version`, optimistic lock / `row_version`).
- Edits create a new version; prior versions remain immutable.
- Allocation and risk results bind to a specific `plan_version_id`.
- Changing plan, allocation, or risk **invalidates** open approvals for the prior snapshot.

## Human approval states

Approval package (`approval_request`) states:

| State | Meaning |
| --- | --- |
| `pending` | Awaiting required approvers |
| `approved` | Quorum/all required roles satisfied |
| `rejected` | At least one required rejection (policy configurable) |
| `invalidated` | Snapshot no longer matches current plan/allocation/risk |
| `expired` | Past TTL without decision |
| `cancelled` | Process cancelled or superseded |

Per-approver decision records: `pending` | `approved` | `rejected` | `abstained` (if allowed).

### Snapshot rules

When entering `awaiting_approval`, persist an **immutable snapshot** containing:

- Plan version payload hash + content
- Allocation payload hash + content
- Risk result payload hash + content
- Required approver roles
- Entitlement/plan tier at request time
- Correlation/trace IDs

Any material change → `invalidated` → process cannot execute on that package.

## Document ingestion lifecycle

| State | Meaning |
| --- | --- |
| `uploaded` | Object stored; metadata recorded |
| `queued` | Awaiting processing |
| `scanning` | Type/size/malware checks (as configured) |
| `extracting` | Text/structure extraction |
| `chunking` | Chunk generation |
| `embedding` | Vector generation (pgvector) |
| `indexed` | Available for retrieval |
| `failed` | Processing failed; retryable or terminal |
| `quarantined` | Safety policy hold |
| `archived` | Soft-retired from active retrieval |

Documents remain tenant-scoped. Agents receive IDs and sanitized excerpts, not raw privileged URLs with service keys.

## Execution substates

While `process.status = executing`:

| Substate | Meaning |
| --- | --- |
| `proposing` | Agent 4 generating tool proposals |
| `gateway_validating` | Schema/AuthZ/idempotency/approval checks |
| `awaiting_tool_approval` | Extra human gate for high-risk tools |
| `invoking_tool` | Adapter call in progress |
| `tool_succeeded` / `tool_failed` | Per-call outcome recorded |
| `compensating` | Optional compensating actions (if defined) |

## Failure and retry behavior

### Classification

| Class | Examples | Behavior |
| --- | --- | --- |
| Transient | Timeouts, 429/5xx from providers | Retry with bounded exponential backoff |
| Validation | Schema/AuthZ failures | No retry; return to user/agent with error code |
| Policy | Compliance fail, injection quarantine | `blocked`; no silent continue |
| Business | Supplier decline | Recorded; workflow branch or human decision |
| Poison | Repeated identical activity crash | Quarantine; alert; manual intervene |

### Retry policy (contract)

- Workflow activities: Temporal (or mock equivalent) retries with max attempts, non-retryable error types for validation/policy.
- Tool gateway: retries only when marked idempotent and safe; same `idempotency_key` must not create duplicate external side effects.
- Agent invocations: retry on provider transient errors; persist last good structured output; do not double-apply side effects (agents don’t apply them).
- Outbox publishers: at-least-once with inbox dedupe by event ID.

### Compensation

- Prefer **draft** artifacts (e.g., PO draft) over irreversible actions until final approval.
- Irreversible tools require stronger approval + explicit audit.
- Compensation actions are themselves gateway tools with idempotency.

## Optimistic locking

- Process plan versions and approval rows use version counters.
- Concurrent updates that lose the race receive conflict errors (`PROCESS_VERSION_CONFLICT`, `APPROVAL_VERSION_CONFLICT`).
- Clients must reload and retry with a new version.

## Audit requirements (workflow-linked)

Every transition, approval decision, invalidation, tool proposal, tool result, and blocker must emit an append-only audit event with actor, org, process, correlation/trace IDs, and payload hashes—not secrets or full sensitive document bodies.

## Realtime updates

State changes publish to SSE channels scoped by org membership and process ACL. Clients display server status; they do not decide legality of transitions.

## Durable orchestration (Temporal Cloud / mock)

- `WORKFLOW_MODE=mock` — in-process durable engine with checkpoints, signals, outbox/inbox, DLQ, and recovery (no Docker).
- `WORKFLOW_MODE=temporal` — Temporal Cloud via `TEMPORAL_HOST` + `TEMPORAL_NAMESPACE` (+ optional `TEMPORAL_API_KEY`); worker is a native process (`scripts/run-worker`).
- Workflow definition version: `bpm.process.v1` (see `app.workflows.versioning`).
- Controls: start, pause, resume, cancel, retry, timeout, human approval wait, missing-information wait, external callback wait, integration-failure recovery.
- Guarantees: outbox events, inbox deduplication / replay protection, workflow trace IDs, agent run records, retry policies, dead-letter on exhausted retries.
