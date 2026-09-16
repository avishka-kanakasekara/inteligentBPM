-- Organization management extensions: profile fields, cost centers,
-- approval authority, supplier approval, and active-email uniqueness.

-- Organization commercial profile
alter table public.organizations
  add column if not exists legal_name text,
  add column if not exists trading_name text,
  add column if not exists industry text,
  add column if not exists country_code text,
  add column if not exists tax_id text,
  add column if not exists tax_registration text,
  add column if not exists tax_country_code text;

-- Settings already holds timezone/currency; add tax metadata bag
alter table public.organization_settings
  add column if not exists tax_information jsonb not null default '{}'::jsonb;

-- Employee directory: manager flag, role label, approval authority
alter table public.employees
  add column if not exists is_manager boolean not null default false,
  add column if not exists role_code text,
  add column if not exists approval_authority_limit numeric(18, 2),
  add column if not exists approval_authority_currency text not null default 'USD';

-- Replace hard unique email with active-only uniqueness so deactivated
-- historical emails remain addressable without blocking reuse.
alter table public.employees drop constraint if exists employees_org_email_unique;

create unique index if not exists employees_org_active_email_unique
  on public.employees (organization_id, lower(email))
  where status = 'active';

-- Cost centers
create table if not exists public.cost_centers (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  code text not null,
  name text not null,
  department_id uuid references public.departments (id) on delete set null,
  status text not null default 'active'
    check (status in ('active', 'inactive')),
  metadata jsonb not null default '{}'::jsonb,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint cost_centers_org_code_unique unique (organization_id, code)
);

create trigger cost_centers_set_updated_at
before update on public.cost_centers
for each row execute function public.set_updated_at();

create index if not exists cost_centers_organization_id_idx
  on public.cost_centers (organization_id);
create index if not exists cost_centers_status_idx
  on public.cost_centers (organization_id, status);

alter table public.budgets
  add column if not exists cost_center_id uuid references public.cost_centers (id) on delete set null;

-- Supplier approval status (independent of operational status)
alter table public.suppliers
  add column if not exists approval_status text not null default 'pending'
    check (approval_status in ('pending', 'approved', 'rejected', 'suspended'));

create index if not exists suppliers_approval_status_idx
  on public.suppliers (organization_id, approval_status);

-- Supplier contact email uniqueness per supplier (active only),
-- unless allow_duplicate_email is explicitly true.
alter table public.supplier_contacts
  add column if not exists allow_duplicate_email boolean not null default false,
  add column if not exists phone text,
  add column if not exists role_title text;

create unique index if not exists supplier_contacts_active_email_unique
  on public.supplier_contacts (supplier_id, lower(email))
  where status = 'active'
    and email is not null
    and allow_duplicate_email = false;

-- Policy metadata
alter table public.policies
  add column if not exists owner_employee_id uuid references public.employees (id) on delete set null,
  add column if not exists metadata jsonb not null default '{}'::jsonb,
  add column if not exists description text;

-- Soft-deactivation: resources use status='inactive' and are never hard-deleted
-- when referenced by historical process snapshots.

-- RLS for cost_centers
alter table public.cost_centers enable row level security;
alter table public.cost_centers force row level security;

grant select, insert, update, delete on public.cost_centers to authenticated;
grant select on public.cost_centers to anon;

create policy cost_centers_select_member
  on public.cost_centers for select to authenticated
  using (public.is_org_member(organization_id));

create policy cost_centers_write_admin
  on public.cost_centers for all to authenticated
  using (public.is_org_admin(organization_id))
  with check (public.is_org_admin(organization_id));
