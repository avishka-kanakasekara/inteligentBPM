-- Store the policy text the management screen shows when a policy is opened.
alter table public.policies
  add column if not exists description text;

alter table public.policies
  add column if not exists owner_employee_id uuid;

alter table public.policies
  add column if not exists metadata jsonb not null default '{}'::jsonb;
