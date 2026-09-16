# Non-container infrastructure notes

This directory holds managed-service configuration references for the BPM platform.

**Docker and container technology are not used.**

## Contents

| Path | Purpose |
| --- | --- |
| `github/` | CI/CD notes mirrored by `.github/workflows` |
| `secrets.example.md` | Secret names for managed host / secret manager (no values) |

Use environment-specific Supabase projects, managed Redis, Temporal Cloud, and managed Python/static hosting as described in `docs/deployment.md`.
