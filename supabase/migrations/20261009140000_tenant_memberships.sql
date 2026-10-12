-- Explicit membership of a Supabase Auth user in a hosted tenant.
-- user_id stores the JWT sub (auth.uid()). It is not a foreign key to
-- public.users or auth.users. This script inserts no rows.
-- RLS is unchanged: existing policies target organization_memberships,
-- and the API enforces membership before it serves tenant data.

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table public.tenant_memberships (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants (id) on delete restrict,
  user_id uuid not null,
  role text not null
    check (role in ('owner', 'admin', 'manager', 'employee', 'compliance', 'auditor')),
  status text not null default 'active'
    check (status in ('active', 'invited', 'suspended', 'removed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint tenant_memberships_tenant_user_unique unique (tenant_id, user_id)
);

create trigger tenant_memberships_set_updated_at
before update on public.tenant_memberships
for each row execute function public.set_updated_at();

create index tenant_memberships_user_status_idx
  on public.tenant_memberships (user_id, status);
