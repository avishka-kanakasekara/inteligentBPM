-- Subscriptions, plan entitlements, and usage metering.
-- Provider secrets stay in the managed secret store / vault — never raw in these tables.

create table if not exists public.plan_catalog (
  plan_code text primary key
    check (plan_code in ('pro', 'enterprise', 'pro_max')),
  display_name text not null,
  description text not null default '',
  sort_order integer not null default 0,
  is_public boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- plan_entitlements / subscriptions / usage_events are created in core_schema_part2.
-- Extend them here only when columns are missing (idempotent for hosted re-runs).
alter table public.subscriptions
  add column if not exists provider text not null default 'mock';
alter table public.subscriptions
  add column if not exists provider_subscription_id text;
alter table public.subscriptions
  add column if not exists cancelled_at timestamptz;
alter table public.subscriptions
  add column if not exists seat_count integer not null default 1;

create index if not exists subscriptions_plan_code_idx on public.subscriptions (plan_code);
create index if not exists subscriptions_status_idx on public.subscriptions (status);
create index if not exists plan_entitlements_plan_code_idx
  on public.plan_entitlements (plan_code);

create table if not exists public.billing_webhook_events (
  id uuid primary key default gen_random_uuid(),
  provider text not null,
  provider_event_id text not null,
  event_type text not null,
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'processed'
    check (status in ('processed', 'ignored', 'failed')),
  error_message text,
  processed_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique (provider, provider_event_id)
);

create index if not exists billing_webhook_events_type_idx
  on public.billing_webhook_events (event_type);

alter table public.plan_entitlements enable row level security;
alter table public.subscriptions enable row level security;
alter table public.usage_events enable row level security;
alter table public.billing_webhook_events enable row level security;
alter table public.plan_catalog enable row level security;

-- Catalog is readable by authenticated users; writes are service-role only.
drop policy if exists plan_catalog_select on public.plan_catalog;
create policy plan_catalog_select on public.plan_catalog
  for select to authenticated using (is_public = true);

drop policy if exists plan_entitlements_select on public.plan_entitlements;
create policy plan_entitlements_select on public.plan_entitlements
  for select to authenticated using (true);

drop policy if exists subscriptions_tenant_select on public.subscriptions;
create policy subscriptions_tenant_select on public.subscriptions
  for select to authenticated
  using (public.is_org_member(organization_id));

drop policy if exists usage_events_tenant_select on public.usage_events;
create policy usage_events_tenant_select on public.usage_events
  for select to authenticated
  using (public.is_org_member(organization_id));

-- Seed plan catalog
insert into public.plan_catalog (plan_code, display_name, description, sort_order)
values
  ('pro', 'Pro', 'One company instance with standard BPM capabilities.', 1),
  ('enterprise', 'Enterprise', 'Multi-org scale with SSO, SCIM, and advanced workflows.', 2),
  ('pro_max', 'Pro Max', 'Highest limits, dedicated capacity, and premium support.', 3)
on conflict (plan_code) do nothing;
