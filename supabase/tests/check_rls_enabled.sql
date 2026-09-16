-- SQL companion checks for hosted Supabase development projects.
-- Prefer pytest in test_rls_security.py for automated assertion.
-- Apply migrations + seed.sql before running.

-- Expect RLS enabled on tenant tables
select c.relname, c.relrowsecurity, c.relforcerowsecurity
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relkind = 'r'
  and c.relname in (
    'organizations', 'employees', 'documents', 'approvals',
    'audit_logs', 'subscriptions', 'document_chunks'
  )
order by 1;
