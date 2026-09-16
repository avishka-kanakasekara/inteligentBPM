# Intelligent BPM Platform

Multi-tenant intelligent business process management platform foundation.

**Docker and container technology are not used.** Local development uses Python virtual environments, Node.js, a hosted Supabase project, Redis (managed or native install), and Temporal Cloud or workflow mock mode.

## Layout

```
apps/web                 React + TypeScript + Vite frontend
services/api             FastAPI backend
services/workflow_worker Native workflow worker (mock/Temporal)
packages/contracts       Shared Pydantic contracts
packages/frontend_types  Shared Zod/TypeScript types
supabase/                SQL migrations, seed, DB tests
docs/                    Product and technical contracts
scripts/                 Native setup/run/check scripts
infra/                   Managed-service notes (no containers)
```

## Quick start (native)

```bash
cp .env.example .env
./scripts/setup-backend
./scripts/setup-frontend
./scripts/run-api        # terminal 1
./scripts/run-worker     # terminal 2 (WORKFLOW_MODE=mock by default)
./scripts/run-frontend   # terminal 3
./scripts/run-tests
./scripts/check
```

See `docs/local-development.md` for full environment setup.

## Health

- `GET /api/v1/healthz` — liveness
- `GET /api/v1/readyz` — readiness (reports missing `DATABASE_URL` / `REDIS_URL` clearly)

## Database

Hosted Supabase only (no local DB containers). Apply migrations with `supabase db push`, seed with `supabase/seed.sql`, and run `./scripts/run-db-tests` when `DATABASE_URL` is set. Details: `docs/database-foundation.md`.
