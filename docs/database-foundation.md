# Database & Supabase Security Foundation

## Scope

This phase adds hosted Supabase PostgreSQL schema, RLS, pgvector search, storage scoping, seed data, and security tests.

**Docker and local database containers are not used.** Develop against environment-specific Supabase projects.

## Migrations

| Migration | Purpose |
| --- | --- |
| `20260915120000_extensions_and_helpers.sql` | pgcrypto, vector, pg_trgm, `set_updated_at` |
| `20260915120100_core_schema_part1.sql` | Tables 1–18 |
| `20260915120200_core_schema_part2.sql` | Tables 19–36 |
| `20260915120300_authz_helpers.sql` | Membership/role helpers for RLS |
| `20260915120400_rls_policies.sql` | RLS + grants for all exposed tenant tables |
| `20260915120500_document_search.sql` | Vector, keyword, and hybrid search |
| `20260915120600_storage_documents.sql` | `documents` bucket + org-scoped storage policies |

## Apply (hosted Supabase)

```bash
supabase login
supabase link --project-ref <dev-project-ref>
supabase db push
# then seed (dev only):
psql "$DATABASE_URL" -f supabase/seed.sql
# or use the SQL editor with seed.sql
```

## Security tests

```bash
export DATABASE_URL='postgresql://...'   # hosted Supabase connection string
./scripts/run-db-tests
```

Tests prove cross-org denial for employees/documents, unauthorized inserts/approvals, append-only audit logs, and org-scoped storage access.

## Seed identities

| Entity | UUID / email |
| --- | --- |
| Demo org | `11111111-1111-1111-1111-111111111111` |
| Other org | `22222222-2222-2222-2222-222222222222` |
| Demo owner | `aaaaaaaa-...` / `owner@demo.bpm.local` |
| Demo employee | `bbbbbbbb-...` / `employee@demo.bpm.local` |
| Other owner | `cccccccc-...` / `owner@other.bpm.local` |

Passwords in seed are local-dev-only placeholders, not production credentials.
