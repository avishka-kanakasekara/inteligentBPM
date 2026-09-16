# Deployment

## Purpose

Managed deployment workflow for local→staging→production without containers.

**Docker and container technology are not used.** Do not deploy via Dockerfiles, container images, Kubernetes, Helm, or container registries.

## Environment topology

| Environment | Supabase | Frontend hosting | Backend hosting | Redis | Temporal | Secrets |
| --- | --- | --- | --- | --- | --- | --- |
| Local | Dev project | Vite dev | Uvicorn in venv | Local or managed | Cloud or mock | `.env` (gitignored) |
| Staging | Staging project | Managed static hosting | Managed Python runtime / native buildpacks | Managed Redis | Temporal Cloud staging namespace | Host secret store |
| Production | Production project | Managed static hosting | Managed Python runtime / native buildpacks | Managed Redis | Temporal Cloud prod namespace | Host/cloud secret manager |

Use **environment-specific Supabase projects**. Never share production database credentials with local or staging clients.

## Frontend deployment (managed static hosting)

1. CI builds the Vite app: `npm ci && npm run build` (or pnpm equivalent).
2. Deploy `dist/` to managed static hosting (e.g., platform-native static site service).
3. Inject only public env: Supabase URL, anon key, API public URL.
4. Configure HTTPS, cache headers for hashed assets, and SPA fallback routing.
5. Set Auth redirect allowlists to the staging/production origins.

## Backend deployment (managed Python)

1. CI installs dependencies with the platform’s **native Python buildpack or managed Python runtime** (no container image build).
2. Run process: ASGI server (e.g., Uvicorn/Gunicorn+Uvicorn workers) binding the platform `PORT`.
3. Deploy a **separate worker process** for Temporal/mock workflows using the same codebase and env.
4. Configure health checks against `/api/v1/healthz` and `/api/v1/readyz`.
5. Attach managed Redis, Supabase, Vertex AI, and Temporal credentials from the secret store.
6. Scale web and worker processes independently via the host platform—not via Kubernetes manifests.

## Database migrations

1. Migrations live in `supabase/migrations/` and are applied per environment explicitly.
2. Staging: apply migrations in CI or a controlled release job against the **staging** project.
3. Production: apply migrations as a gated release step with backups/point-in-time recovery awareness.
4. Application code that depends on a migration must not ship until the migration succeeds.
5. Never run destructive migrations without a reviewed plan.

## CI/CD (GitHub Actions or equivalent)

Suggested pipeline stages:

1. **Lint / typecheck / unit tests** — frontend Vitest + backend Pytest
2. **Contract tests** — API AuthZ and schema contracts
3. **Database security tests** — RLS isolation against staging/dev test project
4. **Playwright** — smoke E2E against staging after deploy (optional gate)
5. **Deploy frontend** — static hosting
6. **Deploy backend web + worker** — managed Python
7. **Migrate** — explicit job with environment protection rules

CI runners must not build or push container images for this application.

## Secrets

- Store secrets in the cloud secret manager or managed hosting secret storage.
- Rotate separately per environment.
- Never commit secrets; `.env.example` contains names/placeholders only—**no fake production credentials**.
- Browser bundle must never receive service role keys, Temporal API keys, or provider secrets.

## Vertex AI / Gemini

- Use official Google Gen AI Python SDK against Vertex AI.
- Configure non-preview model IDs via environment variables.
- Restrict service accounts to least privilege.

## Observability

- Emit structured logs with `correlation_id`, `trace_id`, `organization_id` (when present).
- Redact secrets and sensitive document bodies.
- Alert on workflow failure rates, tool error rates, and auth anomaly signals.

## Rollback

- Frontend: redeploy previous static build artifact.
- Backend: redeploy previous platform release for web and worker.
- Database: prefer forward-fix migrations; rollback SQL only when explicitly prepared.
- Feature flags/entitlements may disable risky features without redeploy when implemented.

## Explicit non-goals

- No Docker/Compose/K8s/Helm/container registry workflows
- No single shared Supabase project across environments
- No LLM direct database or purchasing access in any environment
