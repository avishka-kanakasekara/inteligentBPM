-- Core tenant schema (tables 1–18) for the intelligent BPM platform.
-- Hosted Supabase PostgreSQL only — no local database containers.

-- 1. organizations
create table public.organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text not null,
  status text not null default 'active'
    check (status in ('active', 'suspended', 'deleted')),
  plan_code text not null default 'pro'
    check (plan_code in ('pro', 'enterprise', 'pro_max')),
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint organizations_slug_unique unique (slug)
);

create trigger organizations_set_updated_at
before update on public.organizations
for each row execute function public.set_updated_at();

create index organizations_status_idx on public.organizations (status);
create index organizations_plan_code_idx on public.organizations (plan_code);
create index organizations_created_at_idx on public.organizations (created_at desc);

-- 2. organization_settings
create table public.organization_settings (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  default_timezone text not null default 'UTC',
  default_currency text not null default 'USD',
  notification_preferences jsonb not null default '{}'::jsonb,
  feature_overrides jsonb not null default '{}'::jsonb,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint organization_settings_org_unique unique (organization_id)
);

create trigger organization_settings_set_updated_at
before update on public.organization_settings
for each row execute function public.set_updated_at();

create index organization_settings_organization_id_idx
  on public.organization_settings (organization_id);

-- 3. organization_memberships
create table public.organization_memberships (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  user_id uuid not null,
  role text not null
    check (role in ('owner', 'admin', 'manager', 'employee', 'compliance', 'auditor')),
  status text not null default 'active'
    check (status in ('active', 'invited', 'suspended', 'removed')),
  invited_email text,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint organization_memberships_org_user_unique unique (organization_id, user_id)
);

create trigger organization_memberships_set_updated_at
before update on public.organization_memberships
for each row execute function public.set_updated_at();

create index organization_memberships_organization_id_idx
  on public.organization_memberships (organization_id);
create index organization_memberships_user_id_idx
  on public.organization_memberships (user_id);
create index organization_memberships_status_idx
  on public.organization_memberships (status);
create index organization_memberships_role_idx
  on public.organization_memberships (organization_id, role);

-- 4. employees
create table public.employees (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  user_id uuid,
  employee_code text,
  full_name text not null,
  email text not null,
  title text,
  department_id uuid,
  status text not null default 'active'
    check (status in ('active', 'inactive', 'terminated')),
  metadata jsonb not null default '{}'::jsonb,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint employees_org_email_unique unique (organization_id, email),
  constraint employees_org_code_unique unique (organization_id, employee_code)
);

create trigger employees_set_updated_at
before update on public.employees
for each row execute function public.set_updated_at();

create index employees_organization_id_idx on public.employees (organization_id);
create index employees_user_id_idx on public.employees (user_id);
create index employees_status_idx on public.employees (organization_id, status);
create index employees_department_id_idx on public.employees (department_id);

-- 6. departments (created before FK from employees is enforced)
create table public.departments (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  name text not null,
  code text,
  parent_department_id uuid references public.departments (id) on delete set null,
  manager_employee_id uuid,
  status text not null default 'active'
    check (status in ('active', 'inactive')),
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint departments_org_name_unique unique (organization_id, name),
  constraint departments_org_code_unique unique (organization_id, code)
);

create trigger departments_set_updated_at
before update on public.departments
for each row execute function public.set_updated_at();

create index departments_organization_id_idx on public.departments (organization_id);
create index departments_status_idx on public.departments (organization_id, status);
create index departments_parent_idx on public.departments (parent_department_id);

alter table public.employees
  add constraint employees_department_id_fkey
  foreign key (department_id) references public.departments (id) on delete set null;

alter table public.departments
  add constraint departments_manager_employee_id_fkey
  foreign key (manager_employee_id) references public.employees (id) on delete set null;

-- 5. employee_manager_links
create table public.employee_manager_links (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  employee_id uuid not null references public.employees (id) on delete cascade,
  manager_employee_id uuid not null references public.employees (id) on delete cascade,
  link_type text not null default 'direct'
    check (link_type in ('direct', 'dotted', 'acting')),
  status text not null default 'active'
    check (status in ('active', 'inactive')),
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint employee_manager_links_unique
    unique (organization_id, employee_id, manager_employee_id, link_type),
  constraint employee_manager_links_no_self check (employee_id <> manager_employee_id)
);

create trigger employee_manager_links_set_updated_at
before update on public.employee_manager_links
for each row execute function public.set_updated_at();

create index employee_manager_links_organization_id_idx
  on public.employee_manager_links (organization_id);
create index employee_manager_links_employee_id_idx
  on public.employee_manager_links (employee_id);
create index employee_manager_links_manager_id_idx
  on public.employee_manager_links (manager_employee_id);

-- 7. suppliers
create table public.suppliers (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  name text not null,
  code text,
  status text not null default 'active'
    check (status in ('active', 'inactive', 'blocked')),
  website text,
  country_code text,
  metadata jsonb not null default '{}'::jsonb,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint suppliers_org_name_unique unique (organization_id, name),
  constraint suppliers_org_code_unique unique (organization_id, code)
);

create trigger suppliers_set_updated_at
before update on public.suppliers
for each row execute function public.set_updated_at();

create index suppliers_organization_id_idx on public.suppliers (organization_id);
create index suppliers_status_idx on public.suppliers (organization_id, status);

-- 8. supplier_contacts
create table public.supplier_contacts (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  supplier_id uuid not null references public.suppliers (id) on delete cascade,
  full_name text not null,
  email text,
  phone text,
  role_title text,
  is_primary boolean not null default false,
  status text not null default 'active'
    check (status in ('active', 'inactive')),
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger supplier_contacts_set_updated_at
before update on public.supplier_contacts
for each row execute function public.set_updated_at();

create index supplier_contacts_organization_id_idx
  on public.supplier_contacts (organization_id);
create index supplier_contacts_supplier_id_idx
  on public.supplier_contacts (supplier_id);
create unique index supplier_contacts_primary_unique
  on public.supplier_contacts (supplier_id)
  where is_primary;

-- 9. supplier_products
create table public.supplier_products (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  supplier_id uuid not null references public.suppliers (id) on delete cascade,
  sku text,
  name text not null,
  description text,
  unit_of_measure text,
  unit_price numeric(18, 4),
  currency_code text not null default 'USD',
  status text not null default 'active'
    check (status in ('active', 'inactive', 'discontinued')),
  attributes jsonb not null default '{}'::jsonb,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint supplier_products_org_supplier_sku_unique
    unique (organization_id, supplier_id, sku)
);

create trigger supplier_products_set_updated_at
before update on public.supplier_products
for each row execute function public.set_updated_at();

create index supplier_products_organization_id_idx
  on public.supplier_products (organization_id);
create index supplier_products_supplier_id_idx
  on public.supplier_products (supplier_id);
create index supplier_products_status_idx
  on public.supplier_products (organization_id, status);

-- 10. budgets
create table public.budgets (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  department_id uuid references public.departments (id) on delete set null,
  name text not null,
  fiscal_year integer not null,
  currency_code text not null default 'USD',
  amount_total numeric(18, 2) not null check (amount_total >= 0),
  amount_spent numeric(18, 2) not null default 0 check (amount_spent >= 0),
  status text not null default 'active'
    check (status in ('draft', 'active', 'closed', 'cancelled')),
  metadata jsonb not null default '{}'::jsonb,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint budgets_org_name_year_unique unique (organization_id, name, fiscal_year)
);

create trigger budgets_set_updated_at
before update on public.budgets
for each row execute function public.set_updated_at();

create index budgets_organization_id_idx on public.budgets (organization_id);
create index budgets_department_id_idx on public.budgets (department_id);
create index budgets_status_idx on public.budgets (organization_id, status);

-- 11. policies
create table public.policies (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  code text not null,
  title text not null,
  category text,
  status text not null default 'draft'
    check (status in ('draft', 'active', 'archived')),
  current_version_id uuid,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint policies_org_code_unique unique (organization_id, code)
);

create trigger policies_set_updated_at
before update on public.policies
for each row execute function public.set_updated_at();

create index policies_organization_id_idx on public.policies (organization_id);
create index policies_status_idx on public.policies (organization_id, status);

-- 12. policy_versions
create table public.policy_versions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  policy_id uuid not null references public.policies (id) on delete cascade,
  version_number integer not null check (version_number > 0),
  body_text text not null,
  body_hash text not null,
  effective_from timestamptz,
  effective_to timestamptz,
  status text not null default 'draft'
    check (status in ('draft', 'published', 'superseded')),
  created_by_user_id uuid,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint policy_versions_policy_version_unique unique (policy_id, version_number)
);

create trigger policy_versions_set_updated_at
before update on public.policy_versions
for each row execute function public.set_updated_at();

create index policy_versions_organization_id_idx
  on public.policy_versions (organization_id);
create index policy_versions_policy_id_idx
  on public.policy_versions (policy_id);
create index policy_versions_status_idx
  on public.policy_versions (organization_id, status);

alter table public.policies
  add constraint policies_current_version_id_fkey
  foreign key (current_version_id) references public.policy_versions (id) on delete set null;

-- 13. documents
create table public.documents (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  title text not null,
  document_type text not null default 'general'
    check (document_type in ('general', 'policy', 'process', 'quotation', 'other')),
  storage_bucket text not null default 'documents',
  storage_path text not null,
  mime_type text,
  byte_size bigint check (byte_size is null or byte_size >= 0),
  content_hash text,
  status text not null default 'uploaded'
    check (status in (
      'uploaded', 'queued', 'scanning', 'extracting', 'chunking',
      'embedding', 'indexed', 'failed', 'quarantined', 'archived'
    )),
  uploaded_by_user_id uuid,
  source_policy_id uuid references public.policies (id) on delete set null,
  failure_reason text,
  metadata jsonb not null default '{}'::jsonb,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint documents_org_storage_path_unique unique (organization_id, storage_path)
);

create trigger documents_set_updated_at
before update on public.documents
for each row execute function public.set_updated_at();

create index documents_organization_id_idx on public.documents (organization_id);
create index documents_status_idx on public.documents (organization_id, status);
create index documents_created_at_idx on public.documents (organization_id, created_at desc);
create index documents_type_idx on public.documents (organization_id, document_type);

-- 14. document_chunks
create table public.document_chunks (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  document_id uuid not null references public.documents (id) on delete cascade,
  chunk_index integer not null check (chunk_index >= 0),
  content text not null,
  content_tsv tsvector generated always as (to_tsvector('english', coalesce(content, ''))) stored,
  embedding vector(1536),
  token_count integer check (token_count is null or token_count >= 0),
  metadata jsonb not null default '{}'::jsonb,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint document_chunks_document_index_unique unique (document_id, chunk_index)
);

create trigger document_chunks_set_updated_at
before update on public.document_chunks
for each row execute function public.set_updated_at();

create index document_chunks_organization_id_idx
  on public.document_chunks (organization_id);
create index document_chunks_document_id_idx
  on public.document_chunks (document_id);
create index document_chunks_content_tsv_idx
  on public.document_chunks using gin (content_tsv);
create index document_chunks_embedding_hnsw_idx
  on public.document_chunks
  using hnsw (embedding vector_cosine_ops);

-- 15. process_definitions
create table public.process_definitions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  name text not null,
  description text,
  status text not null default 'draft'
    check (status in ('draft', 'active', 'archived')),
  current_version_id uuid,
  created_by_user_id uuid,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint process_definitions_org_name_unique unique (organization_id, name)
);

create trigger process_definitions_set_updated_at
before update on public.process_definitions
for each row execute function public.set_updated_at();

create index process_definitions_organization_id_idx
  on public.process_definitions (organization_id);
create index process_definitions_status_idx
  on public.process_definitions (organization_id, status);

-- 16. process_versions (immutable plan snapshots)
create table public.process_versions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  process_definition_id uuid not null
    references public.process_definitions (id) on delete cascade,
  version_number integer not null check (version_number > 0),
  plan_snapshot jsonb not null,
  plan_snapshot_hash text not null,
  allocation_snapshot jsonb,
  allocation_snapshot_hash text,
  risk_snapshot jsonb,
  risk_snapshot_hash text,
  status text not null default 'draft'
    check (status in ('draft', 'ready', 'superseded', 'approved', 'rejected')),
  is_immutable boolean not null default false,
  created_by_user_id uuid,
  source_refs jsonb not null default '[]'::jsonb,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint process_versions_definition_version_unique
    unique (process_definition_id, version_number)
);

create trigger process_versions_set_updated_at
before update on public.process_versions
for each row execute function public.set_updated_at();

create or replace function public.prevent_immutable_process_version_mutation()
returns trigger
language plpgsql
as $$
begin
  if tg_op = 'UPDATE' and old.is_immutable then
    if new.plan_snapshot is distinct from old.plan_snapshot
      or new.plan_snapshot_hash is distinct from old.plan_snapshot_hash
      or new.allocation_snapshot is distinct from old.allocation_snapshot
      or new.allocation_snapshot_hash is distinct from old.allocation_snapshot_hash
      or new.risk_snapshot is distinct from old.risk_snapshot
      or new.risk_snapshot_hash is distinct from old.risk_snapshot_hash
      or new.source_refs is distinct from old.source_refs
    then
      raise exception 'Immutable process version snapshots cannot be modified';
    end if;
  end if;
  return new;
end;
$$;

create trigger process_versions_immutable_guard
before update on public.process_versions
for each row execute function public.prevent_immutable_process_version_mutation();

create index process_versions_organization_id_idx
  on public.process_versions (organization_id);
create index process_versions_definition_id_idx
  on public.process_versions (process_definition_id);
create index process_versions_status_idx
  on public.process_versions (organization_id, status);
create index process_versions_hash_idx
  on public.process_versions (organization_id, plan_snapshot_hash);

alter table public.process_definitions
  add constraint process_definitions_current_version_id_fkey
  foreign key (current_version_id) references public.process_versions (id)
  on delete set null;

-- 17. process_steps
create table public.process_steps (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  process_version_id uuid not null
    references public.process_versions (id) on delete cascade,
  step_key text not null,
  title text not null,
  description text,
  step_order integer not null default 0,
  required_capability_tags text[] not null default '{}',
  metadata jsonb not null default '{}'::jsonb,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint process_steps_version_key_unique unique (process_version_id, step_key)
);

create trigger process_steps_set_updated_at
before update on public.process_steps
for each row execute function public.set_updated_at();

create index process_steps_organization_id_idx on public.process_steps (organization_id);
create index process_steps_version_id_idx on public.process_steps (process_version_id);
create index process_steps_order_idx on public.process_steps (process_version_id, step_order);

-- 18. process_edges
create table public.process_edges (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations (id) on delete cascade,
  process_version_id uuid not null
    references public.process_versions (id) on delete cascade,
  from_step_id uuid not null references public.process_steps (id) on delete cascade,
  to_step_id uuid not null references public.process_steps (id) on delete cascade,
  edge_type text not null default 'sequence'
    check (edge_type in ('sequence', 'conditional', 'parallel')),
  condition_expr text,
  metadata jsonb not null default '{}'::jsonb,
  row_version integer not null default 1 check (row_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint process_edges_no_self check (from_step_id <> to_step_id),
  constraint process_edges_unique
    unique (process_version_id, from_step_id, to_step_id, edge_type)
);

create trigger process_edges_set_updated_at
before update on public.process_edges
for each row execute function public.set_updated_at();

create index process_edges_organization_id_idx on public.process_edges (organization_id);
create index process_edges_version_id_idx on public.process_edges (process_version_id);
create index process_edges_from_step_id_idx on public.process_edges (from_step_id);
create index process_edges_to_step_id_idx on public.process_edges (to_step_id);
