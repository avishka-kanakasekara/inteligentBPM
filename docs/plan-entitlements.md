# Plan Entitlements

## Purpose

Server-side feature and usage entitlements for **Pro**, **Enterprise**, and **Pro Max**. The frontend may display plan marketing copy but **must not** decide limits, feature access, or approval bypasses.

**Docker and container technology are not used** for metering or billing workers.

## Plans

| Plan | Positioning |
| --- | --- |
| **Pro** | Growing teams; core discovery → approval → controlled execution |
| **Enterprise** | Stronger compliance, higher limits, advanced integrations |
| **Pro Max** | Highest limits, premium execution volume, expanded connector set |

Exact commercial pricing is out of scope for this contract; technical gates are defined below.

## Entitlement dimensions

1. **Boolean features** — on/off per plan
2. **Numeric quotas** — monthly/period counters with hard or soft caps
3. **Concurrency limits** — parallel processes / agent runs
4. **Retention** — audit/document retention windows
5. **Integration tiers** — which adapters may be enabled

## Feature matrix (contract defaults)

| Feature key | Pro | Enterprise | Pro Max |
| --- | --- | --- | --- |
| `process.discovery` | Yes | Yes | Yes |
| `process.allocation` | Yes | Yes | Yes |
| `process.risk_analysis` | Yes | Yes | Yes |
| `process.execution` | Yes | Yes | Yes |
| `documents.upload` | Yes | Yes | Yes |
| `documents.vector_search` | Yes | Yes | Yes |
| `approvals.multi_role` | Limited | Yes | Yes |
| `audit.export` | Limited | Yes | Yes |
| `integrations.email` | Yes (mock→real) | Yes | Yes |
| `integrations.suppliers` | Basic | Advanced | Advanced+ |
| `integrations.purchasing` | Draft only | Draft + controlled submit* | Draft + controlled submit* |
| `integrations.billing_connector` | No | Optional | Yes |
| `sse.realtime_status` | Yes | Yes | Yes |
| `sso` / `scim` (future) | No | Yes | Yes |
| `dedicated_support_sla` (ops) | No | Yes | Yes |

\*Controlled submit still requires gateway + approvals; never silent purchase.

## Quota matrix (initial defaults — tunable via config)

| Quota key | Pro | Enterprise | Pro Max |
| --- | --- | --- | --- |
| `processes.created_per_month` | 50 | 500 | 5000 |
| `agent_runs.per_month` | 500 | 5000 | 50000 |
| `documents.storage_mb` | 5_000 | 50_000 | 500_000 |
| `documents.uploads_per_day` | 100 | 1_000 | 10_000 |
| `emails.sent_per_month` | 200 | 5_000 | 50_000 |
| `quotation_requests.per_month` | 50 | 1_000 | 10_000 |
| `po_drafts.per_month` | 50 | 1_000 | 10_000 |
| `concurrent_processes` | 5 | 25 | 100 |
| `audit.retention_days` | 90 | 365 | 730+ |

Values are product defaults for implementation; operators may adjust via server config without client trust.

## Enforcement rules

1. Entitlements resolve on the server from `organization.plan` (+ overlays/exceptions stored server-side).
2. Check entitlements in application services **before** expensive agent/tool work.
3. Metering increments after successful billable events; use idempotent meter keys where retries occur.
4. Exceeding hard quotas returns `ENTITLEMENT_DENIED` / `QUOTA_EXCEEDED` with stable codes.
5. Soft caps may warn via notifications but still enforce at hard ceiling.
6. Plan upgrades/downgrades are audited; downgrades must not corrupt history—only block new over-limit actions.
7. Approval status is independent of plan marketing; a plan cannot skip required compliance approvals.

## Usage metering

Billable/metered events (non-exhaustive):

- Process created
- Agent invocation completed (by agent type)
- Document bytes stored / indexed
- Email sent via gateway
- Quotation request sent
- PO draft created / submitted (if allowed)
- Audit export generated

Store per-organization counters with period boundaries (calendar month UTC unless configured otherwise).

## Integration with security

Entitlement checks are necessary but not sufficient: AuthZ + tenant scope + approvals still apply.

## Related documents

- `docs/product-requirements.md`
- `docs/security-model.md`
- `docs/integration-boundaries.md`
- `docs/api-surface.md`
