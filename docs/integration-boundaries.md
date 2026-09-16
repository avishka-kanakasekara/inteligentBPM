# Integration Boundaries

## Purpose

Defines required external integrations, adapter boundaries, mock behavior, and the **tool gateway** as the only path for side effects. LLMs must not call these systems directly.

**Docker and container technology are not used** to run integrations. Adapters execute inside the native FastAPI/worker processes.

## Boundary diagram

```
Agents / Workflows
        │
        ▼
 Typed Tool Gateway  (AuthZ, schema, tenant, idempotency, approval, entitlements, audit)
        │
        ├── Email adapter        → mock | provider API
        ├── Supplier adapter     → mock | supplier/network API
        ├── Purchasing adapter   → mock | ERP/purchasing API
        ├── Billing adapter      → mock | billing provider API
        ├── Notification adapter → in-app + email channel
        └── Storage/LLM/DB       → NOT via agent side-effect tools;
                                   accessed only by application services
```

## Required external integrations

| Integration | Purpose | Side-effecting? |
| --- | --- | --- |
| Supabase Auth | Authentication | Yes (auth provider) |
| Supabase PostgreSQL | System of record | Yes (via app repos only) |
| Supabase Storage | Document blobs | Yes (via document services) |
| Vertex AI / Gemini | Agent reasoning | Yes (model calls; no business side effects) |
| Redis | Cache / rate limits | Yes (infra) |
| Temporal Cloud | Durable workflows | Yes (orchestration) |
| Email provider | Outbound email | Yes — **gateway tool** |
| Supplier / RFQ channel | Quotation collection | Yes — **gateway tool** |
| Purchasing / ERP | PO drafts / submit | Yes — **gateway tool** |
| Billing provider | Subscription/invoices | Yes — **gateway / admin services** |
| Secret manager | Runtime secrets | Infra |

## Tool gateway rules

1. **Single door** for email, supplier RFQ, purchasing, and other business side effects.
2. Validate **tenant scope** using server context.
3. Validate **authorization** permission codes.
4. Validate **input schema** (Pydantic); reject malformed calls.
5. Require **idempotency keys** for all external mutations.
6. Enforce **approval requirements** and snapshot binding when configured.
7. Enforce **plan entitlements** and rate limits.
8. Write **audit events** for propose / deny / execute / result.
9. Return structured results/errors with stable codes.
10. Use **mock adapters** until real credentials exist for that org/environment.

## Mock integrations policy

Until real credentials are provided in environment/org integration settings:

- Email: record message payloads to a mock outbox table/log sink (redacted in logs).
- Suppliers: return deterministic sample quotations labeled `mock=true`.
- Purchasing: create internal PO draft records only; no external submit.
- Billing: simulate plan changes in-app without charging.

Mocks must be obviously marked so demos cannot be mistaken for production sends.

## Adapter interface requirements

- Ports defined in domain/application layers.
- Provider SDKs isolated under `adapters/` (name may vary).
- Timeouts, retries, and circuit breaking configured per adapter.
- No secrets in agent prompts or client responses.
- Per-organization integration config stored encrypted/at-rest protected; decrypted only in backend.

## Idempotency

- Client/workflow supplies idempotency key per logical business action.
- Gateway stores key + org + tool + request hash + outcome.
- Replays return the original outcome without re-invoking the provider when safe.

## Failure behavior

- Transient provider errors → retry per policy if idempotent.
- Permanent errors → fail activity; process may enter `blocked` or `failed`.
- Partial external success with uncertain outcome → surface `TOOL_OUTCOME_UNCERTAIN` for human follow-up; do not invent success.

## What must never be integrations for agents

- Direct PostgreSQL / SQL tools for the LLM
- Direct credentialed email/purchase SDKs inside agent code
- Arbitrary HTTP fetch tools without gateway policy (future additions require ADR)

## Environment credentials

- Local/staging/production use separate provider projects/keys.
- `.env.example` lists variable **names** only—no fake API keys or fake production credentials.
