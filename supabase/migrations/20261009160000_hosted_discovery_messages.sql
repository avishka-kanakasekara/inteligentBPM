-- Hosted discovery chat storage.
--
-- public.processes is owned by a tenant through unique (tenant_id, id).
-- workflow_plans already references that pair. Discovery sessions and messages
-- use the same relationship.
--
-- This script does not change an existing discovery table. The original
-- migration 20260916130000_discovery_and_workflow_artifacts.sql references
-- public.organizations and must not be applied to this hosted database.
-- This script inserts no rows and does not enable or disable row level security.

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

do $migration$
begin
  if to_regclass('public.tenants') is null or to_regclass('public.processes') is null then
    raise notice 'hosted discovery tables skipped: public.tenants or public.processes is absent';
    return;
  end if;
  if to_regclass('public.discovery_sessions') is not null
     or to_regclass('public.discovery_messages') is not null then
    raise notice 'hosted discovery tables skipped: discovery tables already exist';
    return;
  end if;

  create table public.discovery_sessions (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants (id),
    process_id uuid not null references public.processes (id) on delete cascade,
    status text not null default 'active'
      check (status in ('active', 'closed')),
    created_by_user_id uuid,
    document_ids uuid[] not null default '{}'::uuid[],
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    constraint discovery_sessions_tenant_process_fkey
      foreign key (tenant_id, process_id) references public.processes (tenant_id, id),
    constraint discovery_sessions_tenant_process_unique unique (tenant_id, process_id),
    constraint discovery_sessions_tenant_id_unique unique (tenant_id, id)
  );

  create trigger discovery_sessions_set_updated_at
  before update on public.discovery_sessions
  for each row execute function public.set_updated_at();

  create index discovery_sessions_process_id_idx
    on public.discovery_sessions (process_id);

  create table public.discovery_messages (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants (id),
    process_id uuid not null references public.processes (id) on delete cascade,
    session_id uuid not null references public.discovery_sessions (id) on delete cascade,
    role text not null check (role in ('user', 'assistant', 'system')),
    content text not null,
    document_ids uuid[] not null default '{}'::uuid[],
    clarifying_questions jsonb not null default '[]'::jsonb,
    intent jsonb,
    plan_draft jsonb,
    source_refs jsonb not null default '[]'::jsonb,
    suspicious_flags jsonb not null default '[]'::jsonb,
    created_by_user_id uuid,
    created_at timestamptz not null default timezone('utc', now()),
    constraint discovery_messages_tenant_process_fkey
      foreign key (tenant_id, process_id) references public.processes (tenant_id, id),
    constraint discovery_messages_tenant_session_fkey
      foreign key (tenant_id, session_id) references public.discovery_sessions (tenant_id, id)
  );

  create index discovery_messages_tenant_process_created_idx
    on public.discovery_messages (tenant_id, process_id, created_at);
end;
$migration$;
