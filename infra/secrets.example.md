# Secret names (no values)

Populate these in local `.env` or the managed secret store. Do not invent production credentials.

- `DATABASE_URL`
- `REDIS_URL`
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_JWT_SECRET`
- `TEMPORAL_API_KEY` (optional until Temporal mode)
- `GOOGLE_APPLICATION_CREDENTIALS` / Vertex project settings (optional until agents)
- `GOOGLE_API_KEY` / `GEMINI_API_KEY` (Gemini Developer API; use instead of a Vertex JSON key file)
- Email / supplier / purchasing / billing keys (optional; mocks used when empty)
