-- Durable Agent 4 side-effect artifacts (documents, calendar, tasks, notifications, tools, email).

create table if not exists public.app_execution_artifacts (
  id uuid primary key,
  organization_id uuid not null references public.organizations (id) on delete cascade,
  process_id uuid,
  process_run_id uuid,
  artifact_kind text not null
    check (artifact_kind in (
      'notification',
      'calendar_event',
      'task',
      'generated_document',
      'tool_invocation',
      'email'
    )),
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger app_execution_artifacts_set_updated_at
before update on public.app_execution_artifacts
for each row execute function public.set_updated_at();

create index if not exists app_execution_artifacts_org_kind_idx
  on public.app_execution_artifacts (organization_id, artifact_kind, created_at desc);

create index if not exists app_execution_artifacts_process_idx
  on public.app_execution_artifacts (organization_id, process_id);
