-- Discovery chat persistence and workflow artifact storage for API postgres mode.

-- Extend process version statuses used by the API runtime.
alter table public.process_versions
  drop constraint if exists process_versions_status_check;

alter table public.process_versions
  add constraint process_versions_status_check
  check (status in ('draft', 'ready', 'confirmed', 'superseded', 'approved', 'rejected'));

-- Discovery sessions (Agent 1 chat)
create table if not exists public.discovery_sessions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  process_definition_id uuid not null references public.process_definitions (id) on delete cascade,
  status text not null default 'active'
    check (status in ('active', 'closed')),
  created_by_user_id uuid,
  document_ids uuid[] not null default '{}'::uuid[],
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint discovery_sessions_org_process_unique unique (organization_id, process_definition_id)
);

create trigger discovery_sessions_set_updated_at
before update on public.discovery_sessions
for each row execute function public.set_updated_at();

create index if not exists discovery_sessions_organization_id_idx
  on public.discovery_sessions (organization_id);
create index if not exists discovery_sessions_process_id_idx
  on public.discovery_sessions (process_definition_id);

-- Discovery messages
create table if not exists public.discovery_messages (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  process_definition_id uuid not null references public.process_definitions (id) on delete cascade,
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
  created_at timestamptz not null default now()
);

create index if not exists discovery_messages_organization_id_idx
  on public.discovery_messages (organization_id);
create index if not exists discovery_messages_process_id_idx
  on public.discovery_messages (process_definition_id, created_at);

-- Allocation / risk / approval snapshots keyed by process version
create table if not exists public.process_workflow_artifacts (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  process_definition_id uuid not null references public.process_definitions (id) on delete cascade,
  process_version_id uuid not null references public.process_versions (id) on delete cascade,
  artifact_type text not null
    check (artifact_type in ('allocation', 'risk', 'approval')),
  status text not null,
  payload jsonb not null default '{}'::jsonb,
  plan_snapshot_hash text,
  allocation_snapshot_hash text,
  risk_snapshot_hash text,
  valid boolean,
  invalidated_reason text,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint process_workflow_artifacts_version_type_unique
    unique (process_version_id, artifact_type)
);

create trigger process_workflow_artifacts_set_updated_at
before update on public.process_workflow_artifacts
for each row execute function public.set_updated_at();

create index if not exists process_workflow_artifacts_org_idx
  on public.process_workflow_artifacts (organization_id);
create index if not exists process_workflow_artifacts_process_idx
  on public.process_workflow_artifacts (process_definition_id);

-- In-app process runs (lighterweight than full workflow orchestration tables)
create table if not exists public.app_process_runs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  process_definition_id uuid not null references public.process_definitions (id) on delete cascade,
  process_version_id uuid references public.process_versions (id) on delete set null,
  status text not null,
  initiated_by_user_id uuid,
  correlation_id text,
  plan_snapshot_hash text,
  risk_snapshot_hash text,
  approval_id uuid,
  dry_run boolean not null default false,
  current_step_index integer not null default 0,
  pause_reason text,
  allowed_tools jsonb not null default '[]'::jsonb,
  metadata jsonb not null default '{}'::jsonb,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger app_process_runs_set_updated_at
before update on public.app_process_runs
for each row execute function public.set_updated_at();

create index if not exists app_process_runs_org_idx
  on public.app_process_runs (organization_id, created_at desc);
