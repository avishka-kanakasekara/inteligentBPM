# Local Development

## Purpose

Native local development workflow for the intelligent BPM platform. **Docker and container technology are not used**—do not create or follow Dockerfiles, Compose files, or container-based instructions.

Local development uses:

- Python virtual environments
- Node.js with npm or pnpm
- A **hosted Supabase development project** (not an assumed local Postgres; this project standardizes on hosted Supabase)
- A **managed Redis** instance or **locally installed Redis**
- **Temporal Cloud** (dev namespace) or **native workflow mock/test mode**
- **Mock integrations** for email, suppliers, purchasing, and billing until real credentials are configured

## Prerequisites

| Tool | Notes |
| --- | --- |
| Python 3.12+ (recommended) | For FastAPI backend and workers |
| Node.js 20+ LTS | For Vite React frontend |
| npm or pnpm | Frontend package manager |
| Supabase CLI (optional but recommended) | Link project and run SQL migrations against hosted Supabase |
| Redis | Local install (e.g., Homebrew `redis`) **or** managed Redis URL |
| Git | Source control |
| Google Cloud access (optional initially) | Vertex AI / Gemini; mocks until configured |

Do **not** install Docker for this project.

## Repository layout

```
apps/web/                     React + TypeScript + Vite
services/api/                 FastAPI + SQLAlchemy
services/workflow_worker/     Native worker (mock or Temporal Cloud)
packages/contracts/           Shared Pydantic contracts
packages/frontend_types/      Shared Zod / TypeScript types
supabase/migrations/          SQL migrations
supabase/seed.sql             Dev seed
supabase/tests/               DB security SQL checks
docs/                         Product and technical contracts
scripts/                      Native setup/run/check scripts
infra/                        Managed-service notes (no containers)
.env.example                  Variable names only
```

## Environment variable setup

1. `cp .env.example .env`
2. Optionally `cp apps/web/.env.example apps/web/.env` and set public Vite vars.
3. Fill values from your **Supabase development project**, Redis, and optional Temporal/Vertex credentials.
4. **Never commit** `.env` or real secrets.
5. Leave optional integrations empty to use mocks. Do not invent fake production credentials.

## Python virtual environment creation

Preferred:

```bash
./scripts/setup-backend
source .venv/bin/activate
```

Manual equivalent:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e "./packages/contracts[dev]"
pip install -e "./services/api[dev]"
pip install -e "./services/workflow_worker[dev]"
```

## Node.js installation requirements

- Install **Node.js 20+ LTS**.
- Confirm with `node -v` and `npm -v` (or `pnpm -v`).

## Frontend dependency installation

```bash
./scripts/setup-frontend
```

Or:

```bash
npm install --prefix packages/frontend_types
npm install --prefix apps/web
```

Never place service-role keys in `apps/web` env files.

## Backend dependency installation

Handled by `./scripts/setup-backend` (venv + editable installs).

## Supabase project configuration

1. Create a **development** project in the Supabase dashboard (separate from staging/production).
2. Copy Project URL, anon key, and service role key into `.env` (service role **backend only**).
3. Enable extensions required by migrations (including `vector`).
4. Configure Auth redirect URLs for `http://localhost:5173`.
5. Apply storage policies when document features land.

Do not assume a local PostgreSQL server when Supabase is the database provider.

## Supabase migration execution

```bash
supabase login
supabase link --project-ref <your-dev-project-ref>
supabase db push
psql "$DATABASE_URL" -f supabase/seed.sql
```

See `docs/database-foundation.md` for the full table list, RLS posture, search functions, and DB security tests:

```bash
export DATABASE_URL='postgresql://...'  # hosted Supabase development DB
./scripts/run-db-tests
```

Do not use local database containers.

## Redis configuration

**Local install (macOS example):**

```bash
brew install redis
brew services start redis
# REDIS_URL=redis://127.0.0.1:6379/0
```

**Managed Redis:** set `REDIS_URL` in `.env`.

## Temporal Cloud configuration or workflow mock mode

- Mock (default): `WORKFLOW_MODE=mock` then `./scripts/run-worker`
- Temporal Cloud: set `TEMPORAL_HOST`, `TEMPORAL_NAMESPACE`, `TEMPORAL_API_KEY`, and `WORKFLOW_MODE=temporal` (client wiring completes when credentials are available)

## Running the FastAPI backend

```bash
./scripts/run-api
```

Health: `GET http://localhost:8000/api/v1/healthz`  
Readiness: `GET http://localhost:8000/api/v1/readyz`

## Running the frontend

```bash
./scripts/run-frontend
```

Default Vite URL: `http://localhost:5173`.

## Running the workflow worker

```bash
./scripts/run-worker
```

## Running tests and checks

```bash
./scripts/run-tests
./scripts/check
```

Includes Pytest, Vitest, Ruff, MyPy, frontend typecheck/build, and a guard that no Docker files are required.

## What not to do locally

- Do not introduce Docker/Compose/Kubernetes.
- Do not commit secrets or use production Supabase keys.
- Do not hardcode preview Gemini model IDs.
- Do not disable RLS on shared projects without a restoration plan.
