-- Core tenant schema (tables 19–36) for the intelligent BPM platform.

-- 19. process_runs
create table public.process_runs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  process_definition_id uuid not null
    references public.process_definitions (id) on delete restrict,
  process_version_id uuid not null
    references public.process_versions (id) on delete restrict,
  status text not null default 'draft'
    check (status in (
      'draft', 'discovering', 'plan_ready', 'allocating', 'allocated',
      'analyzing_risk', 'risk_complete', 'awaiting_approval', 'approved',
      'rejected', 'executing', 'blocked', 'failed', 'completed', 'cancelled'
    )),
  correlation_id text,
  trace_id text,
  initiated_by_user_id uuid,
  current_approval_id uuid,
  failure_reason text,
  metadata jsonb not null default '{}'::jsonb,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger process_runs_set_updated_at
before update on public.process_runs
for each row execute function public.set_updated_at();

create index process_runs_organization_id_idx on public.process_runs (organization_id);
create index process_runs_status_idx on public.process_runs (organization_id, status);
create index process_runs_definition_id_idx on public.process_runs (process_definition_id);
create index process_runs_version_id_idx on public.process_runs (process_version_id);
create index process_runs_created_at_idx on public.process_runs (organization_id, created_at desc);
create index process_runs_correlation_id_idx on public.process_runs (correlation_id);

-- 20. process_step_runs
create table public.process_step_runs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  process_run_id uuid not null references public.process_runs (id) on delete cascade,
  process_step_id uuid not null references public.process_steps (id) on delete restrict,
  status text not null default 'pending'
    check (status in (
      'pending', 'ready', 'running', 'waiting_approval', 'succeeded',
      'failed', 'skipped', 'cancelled', 'blocked'
    )),
  started_at timestamptz,
  finished_at timestamptz,
  assigned_employee_id uuid references public.employees (id) on delete set null,
  output_summary text,
  source_refs jsonb not null default '[]'::jsonb,
  metadata jsonb not null default '{}'::jsonb,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint process_step_runs_unique unique (process_run_id, process_step_id)
);

create trigger process_step_runs_set_updated_at
before update on public.process_step_runs
for each row execute function public.set_updated_at();

create index process_step_runs_organization_id_idx
  on public.process_step_runs (organization_id);
create index process_step_runs_run_id_idx on public.process_step_runs (process_run_id);
create index process_step_runs_status_idx
  on public.process_step_runs (organization_id, status);

-- 21. agent_runs
create table public.agent_runs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  process_run_id uuid references public.process_runs (id) on delete cascade,
  agent_type text not null
    check (agent_type in (
      'discovery_planning',
      'resource_allocation',
      'risk_compliance',
      'controlled_execution'
    )),
  status text not null default 'queued'
    check (status in ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
  model_id text,
  correlation_id text,
  trace_id text,
  reasoning_summary text,
  structured_output jsonb,
  source_refs jsonb not null default '[]'::jsonb,
  error_code text,
  error_message text,
  started_at timestamptz,
  finished_at timestamptz,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger agent_runs_set_updated_at
before update on public.agent_runs
for each row execute function public.set_updated_at();

create index agent_runs_organization_id_idx on public.agent_runs (organization_id);
create index agent_runs_process_run_id_idx on public.agent_runs (process_run_id);
create index agent_runs_status_idx on public.agent_runs (organization_id, status);
create index agent_runs_agent_type_idx on public.agent_runs (organization_id, agent_type);

-- 22. agent_messages
create table public.agent_messages (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  agent_run_id uuid not null references public.agent_runs (id) on delete cascade,
  role text not null
    check (role in ('system', 'user', 'assistant', 'tool')),
  sequence_no integer not null check (sequence_no >= 0),
  content text,
  tool_call_id text,
  tool_name text,
  structured_payload jsonb,
  source_refs jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint agent_messages_run_sequence_unique unique (agent_run_id, sequence_no)
);

create trigger agent_messages_set_updated_at
before update on public.agent_messages
for each row execute function public.set_updated_at();

create index agent_messages_organization_id_idx on public.agent_messages (organization_id);
create index agent_messages_agent_run_id_idx on public.agent_messages (agent_run_id);

-- 23. approvals
create table public.approvals (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  process_run_id uuid not null references public.process_runs (id) on delete cascade,
  process_version_id uuid not null
    references public.process_versions (id) on delete restrict,
  status text not null default 'pending'
    check (status in (
      'pending', 'approved', 'rejected', 'invalidated', 'expired', 'cancelled'
    )),
  required_roles text[] not null default '{}',
  snapshot_plan_hash text not null,
  snapshot_allocation_hash text,
  snapshot_risk_hash text,
  snapshot_payload jsonb not null,
  snapshot_hash text not null,
  decided_by_user_id uuid,
  decision_note text,
  expires_at timestamptz,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger approvals_set_updated_at
before update on public.approvals
for each row execute function public.set_updated_at();

create index approvals_organization_id_idx on public.approvals (organization_id);
create index approvals_process_run_id_idx on public.approvals (process_run_id);
create index approvals_status_idx on public.approvals (organization_id, status);
create index approvals_snapshot_hash_idx on public.approvals (organization_id, snapshot_hash);

alter table public.process_runs
  add constraint process_runs_current_approval_id_fkey
  foreign key (current_approval_id) references public.approvals (id)
  on delete set null;

-- 24. tool_calls
create table public.tool_calls (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  process_run_id uuid references public.process_runs (id) on delete cascade,
  agent_run_id uuid references public.agent_runs (id) on delete set null,
  approval_id uuid references public.approvals (id) on delete set null,
  tool_name text not null,
  status text not null default 'proposed'
    check (status in (
      'proposed', 'validated', 'denied', 'awaiting_approval',
      'invoking', 'succeeded', 'failed', 'uncertain'
    )),
  idempotency_key text not null,
  request_metadata jsonb not null default '{}'::jsonb,
  response_metadata jsonb not null default '{}'::jsonb,
  error_code text,
  error_message text,
  -- Never store secrets/tokens in metadata JSONB fields.
  requires_approval boolean not null default false,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint tool_calls_org_idempotency_unique unique (organization_id, idempotency_key)
);

create trigger tool_calls_set_updated_at
before update on public.tool_calls
for each row execute function public.set_updated_at();

create index tool_calls_organization_id_idx on public.tool_calls (organization_id);
create index tool_calls_process_run_id_idx on public.tool_calls (process_run_id);
create index tool_calls_status_idx on public.tool_calls (organization_id, status);
create index tool_calls_tool_name_idx on public.tool_calls (organization_id, tool_name);

-- 25. integration_connections
create table public.integration_connections (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  provider text not null
    check (provider in ('email', 'supplier', 'purchasing', 'billing', 'other')),
  display_name text not null,
  status text not null default 'disabled'
    check (status in ('disabled', 'mock', 'active', 'error')),
  config jsonb not null default '{}'::jsonb,
  -- Secrets must live in secret manager / vault references, not plaintext here.
  secret_ref text,
  last_error text,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint integration_connections_org_provider_name_unique
    unique (organization_id, provider, display_name)
);

create trigger integration_connections_set_updated_at
before update on public.integration_connections
for each row execute function public.set_updated_at();

create index integration_connections_organization_id_idx
  on public.integration_connections (organization_id);
create index integration_connections_status_idx
  on public.integration_connections (organization_id, status);

-- 26. quotations
create table public.quotations (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  process_run_id uuid references public.process_runs (id) on delete set null,
  supplier_id uuid not null references public.suppliers (id) on delete restrict,
  status text not null default 'draft'
    check (status in (
      'draft', 'requested', 'received', 'compared', 'accepted', 'rejected', 'expired'
    )),
  currency_code text not null default 'USD',
  total_amount numeric(18, 2),
  valid_until timestamptz,
  external_reference text,
  is_mock boolean not null default true,
  metadata jsonb not null default '{}'::jsonb,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger quotations_set_updated_at
before update on public.quotations
for each row execute function public.set_updated_at();

create index quotations_organization_id_idx on public.quotations (organization_id);
create index quotations_supplier_id_idx on public.quotations (supplier_id);
create index quotations_process_run_id_idx on public.quotations (process_run_id);
create index quotations_status_idx on public.quotations (organization_id, status);

-- 27. quotation_items
create table public.quotation_items (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  quotation_id uuid not null references public.quotations (id) on delete cascade,
  supplier_product_id uuid references public.supplier_products (id) on delete set null,
  line_number integer not null check (line_number > 0),
  description text not null,
  quantity numeric(18, 4) not null check (quantity >= 0),
  unit_price numeric(18, 4) not null check (unit_price >= 0),
  line_total numeric(18, 2) not null check (line_total >= 0),
  metadata jsonb not null default '{}'::jsonb,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint quotation_items_quotation_line_unique unique (quotation_id, line_number)
);

create trigger quotation_items_set_updated_at
before update on public.quotation_items
for each row execute function public.set_updated_at();

create index quotation_items_organization_id_idx
  on public.quotation_items (organization_id);
create index quotation_items_quotation_id_idx on public.quotation_items (quotation_id);

-- 28. purchase_orders
create table public.purchase_orders (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  process_run_id uuid references public.process_runs (id) on delete set null,
  supplier_id uuid not null references public.suppliers (id) on delete restrict,
  quotation_id uuid references public.quotations (id) on delete set null,
  status text not null default 'draft'
    check (status in (
      'draft', 'pending_approval', 'approved', 'submitted', 'rejected', 'cancelled'
    )),
  currency_code text not null default 'USD',
  total_amount numeric(18, 2),
  external_reference text,
  is_mock boolean not null default true,
  approval_id uuid references public.approvals (id) on delete set null,
  metadata jsonb not null default '{}'::jsonb,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger purchase_orders_set_updated_at
before update on public.purchase_orders
for each row execute function public.set_updated_at();

create index purchase_orders_organization_id_idx
  on public.purchase_orders (organization_id);
create index purchase_orders_supplier_id_idx on public.purchase_orders (supplier_id);
create index purchase_orders_status_idx
  on public.purchase_orders (organization_id, status);
create index purchase_orders_process_run_id_idx
  on public.purchase_orders (process_run_id);

-- 29. notifications
create table public.notifications (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  user_id uuid not null,
  channel text not null default 'in_app'
    check (channel in ('in_app', 'email')),
  title text not null,
  body text not null,
  status text not null default 'unread'
    check (status in ('unread', 'read', 'archived')),
  resource_type text,
  resource_id uuid,
  metadata jsonb not null default '{}'::jsonb,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger notifications_set_updated_at
before update on public.notifications
for each row execute function public.set_updated_at();

create index notifications_organization_id_idx on public.notifications (organization_id);
create index notifications_user_id_idx on public.notifications (user_id);
create index notifications_status_idx on public.notifications (organization_id, user_id, status);
create index notifications_created_at_idx
  on public.notifications (organization_id, created_at desc);

-- 30. audit_logs (append-only)
create table public.audit_logs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  actor_user_id uuid,
  actor_type text not null default 'user'
    check (actor_type in ('user', 'system', 'agent', 'workflow')),
  action text not null,
  resource_type text not null,
  resource_id uuid,
  correlation_id text,
  trace_id text,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
  -- intentionally no updated_at; append-only
);

create index audit_logs_organization_id_idx on public.audit_logs (organization_id);
create index audit_logs_created_at_idx on public.audit_logs (organization_id, created_at desc);
create index audit_logs_resource_idx
  on public.audit_logs (organization_id, resource_type, resource_id);
create index audit_logs_actor_user_id_idx on public.audit_logs (actor_user_id);
create index audit_logs_action_idx on public.audit_logs (organization_id, action);

create or replace function public.deny_audit_log_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception 'audit_logs are append-only';
end;
$$;

create trigger audit_logs_deny_update
before update on public.audit_logs
for each row execute function public.deny_audit_log_mutation();

create trigger audit_logs_deny_delete
before delete on public.audit_logs
for each row execute function public.deny_audit_log_mutation();

-- 32. plan_entitlements (global catalog; not tenant-owned)
create table public.plan_entitlements (
  id uuid primary key default gen_random_uuid(),
  plan_code text not null
    check (plan_code in ('pro', 'enterprise', 'pro_max')),
  feature_key text not null,
  entitlement_type text not null
    check (entitlement_type in ('boolean', 'quota', 'concurrency', 'retention')),
  boolean_value boolean,
  numeric_value numeric,
  unit text,
  description text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint plan_entitlements_plan_feature_unique unique (plan_code, feature_key)
);

create trigger plan_entitlements_set_updated_at
before update on public.plan_entitlements
for each row execute function public.set_updated_at();

create index plan_entitlements_plan_code_idx on public.plan_entitlements (plan_code);

-- 31. subscriptions
create table public.subscriptions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  plan_code text not null
    check (plan_code in ('pro', 'enterprise', 'pro_max')),
  status text not null default 'active'
    check (status in ('trialing', 'active', 'past_due', 'cancelled', 'expired')),
  current_period_start timestamptz not null default now(),
  current_period_end timestamptz,
  cancel_at_period_end boolean not null default false,
  external_customer_ref text,
  external_subscription_ref text,
  metadata jsonb not null default '{}'::jsonb,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint subscriptions_org_unique unique (organization_id)
);

create trigger subscriptions_set_updated_at
before update on public.subscriptions
for each row execute function public.set_updated_at();

create index subscriptions_organization_id_idx on public.subscriptions (organization_id);
create index subscriptions_status_idx on public.subscriptions (status);
create index subscriptions_plan_code_idx on public.subscriptions (plan_code);

-- 33. usage_events
create table public.usage_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  meter_key text not null,
  quantity numeric not null default 1 check (quantity >= 0),
  period_start timestamptz not null,
  period_end timestamptz not null,
  idempotency_key text not null,
  resource_type text,
  resource_id uuid,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint usage_events_org_idempotency_unique unique (organization_id, idempotency_key)
);

create trigger usage_events_set_updated_at
before update on public.usage_events
for each row execute function public.set_updated_at();

create index usage_events_organization_id_idx on public.usage_events (organization_id);
create index usage_events_meter_key_idx
  on public.usage_events (organization_id, meter_key, period_start);
create index usage_events_created_at_idx
  on public.usage_events (organization_id, created_at desc);

-- 34. idempotency_keys
create table public.idempotency_keys (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  key text not null,
  scope text not null,
  request_hash text not null,
  response_status integer,
  response_body jsonb,
  status text not null default 'in_progress'
    check (status in ('in_progress', 'completed', 'failed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint idempotency_keys_org_scope_key_unique unique (organization_id, scope, key)
);

create trigger idempotency_keys_set_updated_at
before update on public.idempotency_keys
for each row execute function public.set_updated_at();

create index idempotency_keys_organization_id_idx
  on public.idempotency_keys (organization_id);
create index idempotency_keys_status_idx
  on public.idempotency_keys (organization_id, status);
create index idempotency_keys_created_at_idx
  on public.idempotency_keys (organization_id, created_at desc);

-- 35. outbox_events
create table public.outbox_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  event_type text not null,
  aggregate_type text not null,
  aggregate_id uuid not null,
  payload jsonb not null,
  status text not null default 'pending'
    check (status in ('pending', 'publishing', 'published', 'failed')),
  attempts integer not null default 0 check (attempts >= 0),
  available_at timestamptz not null default now(),
  published_at timestamptz,
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger outbox_events_set_updated_at
before update on public.outbox_events
for each row execute function public.set_updated_at();

create index outbox_events_organization_id_idx on public.outbox_events (organization_id);
create index outbox_events_status_available_idx
  on public.outbox_events (status, available_at);
create index outbox_events_aggregate_idx
  on public.outbox_events (organization_id, aggregate_type, aggregate_id);

-- 36. inbox_events
create table public.inbox_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  event_id uuid not null,
  event_type text not null,
  payload jsonb not null,
  status text not null default 'received'
    check (status in ('received', 'processed', 'failed', 'ignored')),
  processed_at timestamptz,
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint inbox_events_org_event_unique unique (organization_id, event_id)
);

create trigger inbox_events_set_updated_at
before update on public.inbox_events
for each row execute function public.set_updated_at();

create index inbox_events_organization_id_idx on public.inbox_events (organization_id);
create index inbox_events_status_idx on public.inbox_events (organization_id, status);
create index inbox_events_created_at_idx
  on public.inbox_events (organization_id, created_at desc);
