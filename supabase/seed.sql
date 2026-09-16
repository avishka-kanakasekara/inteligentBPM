-- Development seed for hosted Supabase development projects only.
-- Do not run against production. Contains no real secrets or production credentials.
-- Docker/local database containers are not used.

-- Fixed demo identities
-- org A (demo): 11111111-1111-1111-1111-111111111111
-- org B (other): 22222222-2222-2222-2222-222222222222
-- owner A:       aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa
-- employee A:    bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb
-- owner B:       cccccccc-cccc-cccc-cccc-cccccccccccc

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- Auth users (hosted Supabase auth schema)
-- ---------------------------------------------------------------------------
insert into auth.users (
  instance_id,
  id,
  aud,
  role,
  email,
  encrypted_password,
  email_confirmed_at,
  raw_app_meta_data,
  raw_user_meta_data,
  created_at,
  updated_at,
  confirmation_token,
  recovery_token,
  email_change_token_new,
  email_change
)
values
  (
    '00000000-0000-0000-0000-000000000000',
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    'authenticated',
    'authenticated',
    'owner@demo.bpm.local',
    crypt('local-dev-only', gen_salt('bf')),
    now(),
    '{"provider":"email","providers":["email"]}'::jsonb,
    '{"full_name":"Demo Owner"}'::jsonb,
    now(),
    now(),
    '',
    '',
    '',
    ''
  ),
  (
    '00000000-0000-0000-0000-000000000000',
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
    'authenticated',
    'authenticated',
    'employee@demo.bpm.local',
    crypt('local-dev-only', gen_salt('bf')),
    now(),
    '{"provider":"email","providers":["email"]}'::jsonb,
    '{"full_name":"Demo Employee"}'::jsonb,
    now(),
    now(),
    '',
    '',
    '',
    ''
  ),
  (
    '00000000-0000-0000-0000-000000000000',
    'cccccccc-cccc-cccc-cccc-cccccccccccc',
    'authenticated',
    'authenticated',
    'owner@other.bpm.local',
    crypt('local-dev-only', gen_salt('bf')),
    now(),
    '{"provider":"email","providers":["email"]}'::jsonb,
    '{"full_name":"Other Org Owner"}'::jsonb,
    now(),
    now(),
    '',
    '',
    '',
    ''
  )
on conflict (id) do nothing;

insert into auth.identities (
  id,
  user_id,
  identity_data,
  provider,
  provider_id,
  last_sign_in_at,
  created_at,
  updated_at
)
values
  (
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    jsonb_build_object('sub', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'email', 'owner@demo.bpm.local'),
    'email',
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    now(),
    now(),
    now()
  ),
  (
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
    jsonb_build_object('sub', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'email', 'employee@demo.bpm.local'),
    'email',
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
    now(),
    now(),
    now()
  ),
  (
    'cccccccc-cccc-cccc-cccc-cccccccccccc',
    'cccccccc-cccc-cccc-cccc-cccccccccccc',
    jsonb_build_object('sub', 'cccccccc-cccc-cccc-cccc-cccccccccccc', 'email', 'owner@other.bpm.local'),
    'email',
    'cccccccc-cccc-cccc-cccc-cccccccccccc',
    now(),
    now(),
    now()
  )
on conflict do nothing;

-- ---------------------------------------------------------------------------
-- Plan entitlements: Pro, Enterprise, Pro Max
-- ---------------------------------------------------------------------------
insert into public.plan_entitlements (
  plan_code, feature_key, entitlement_type, boolean_value, numeric_value, unit, description
)
values
  ('pro', 'process.discovery', 'boolean', true, null, null, 'Process discovery'),
  ('pro', 'process.execution', 'boolean', true, null, null, 'Controlled execution'),
  ('pro', 'processes.created_per_month', 'quota', null, 50, 'count', 'Monthly processes'),
  ('pro', 'documents.storage_mb', 'quota', null, 5000, 'mb', 'Document storage'),
  ('pro', 'concurrent_processes', 'concurrency', null, 5, 'count', 'Concurrent processes'),
  ('pro', 'audit.retention_days', 'retention', null, 90, 'days', 'Audit retention'),
  ('enterprise', 'process.discovery', 'boolean', true, null, null, 'Process discovery'),
  ('enterprise', 'process.execution', 'boolean', true, null, null, 'Controlled execution'),
  ('enterprise', 'approvals.multi_role', 'boolean', true, null, null, 'Multi-role approvals'),
  ('enterprise', 'processes.created_per_month', 'quota', null, 500, 'count', 'Monthly processes'),
  ('enterprise', 'documents.storage_mb', 'quota', null, 50000, 'mb', 'Document storage'),
  ('enterprise', 'concurrent_processes', 'concurrency', null, 25, 'count', 'Concurrent processes'),
  ('enterprise', 'audit.retention_days', 'retention', null, 365, 'days', 'Audit retention'),
  ('pro_max', 'process.discovery', 'boolean', true, null, null, 'Process discovery'),
  ('pro_max', 'process.execution', 'boolean', true, null, null, 'Controlled execution'),
  ('pro_max', 'approvals.multi_role', 'boolean', true, null, null, 'Multi-role approvals'),
  ('pro_max', 'processes.created_per_month', 'quota', null, 5000, 'count', 'Monthly processes'),
  ('pro_max', 'documents.storage_mb', 'quota', null, 500000, 'mb', 'Document storage'),
  ('pro_max', 'concurrent_processes', 'concurrency', null, 100, 'count', 'Concurrent processes'),
  ('pro_max', 'audit.retention_days', 'retention', null, 730, 'days', 'Audit retention')
on conflict (plan_code, feature_key) do update
set
  entitlement_type = excluded.entitlement_type,
  boolean_value = excluded.boolean_value,
  numeric_value = excluded.numeric_value,
  unit = excluded.unit,
  description = excluded.description,
  updated_at = now();

-- ---------------------------------------------------------------------------
-- Organizations
-- ---------------------------------------------------------------------------
insert into public.organizations (id, name, slug, status, plan_code)
values
  (
    '11111111-1111-1111-1111-111111111111',
    'Demo Organization',
    'demo-organization',
    'active',
    'pro'
  ),
  (
    '22222222-2222-2222-2222-222222222222',
    'Other Organization',
    'other-organization',
    'active',
    'enterprise'
  )
on conflict (id) do nothing;

insert into public.organization_settings (organization_id, default_timezone, default_currency)
values
  ('11111111-1111-1111-1111-111111111111', 'UTC', 'USD'),
  ('22222222-2222-2222-2222-222222222222', 'UTC', 'USD')
on conflict (organization_id) do nothing;

insert into public.subscriptions (organization_id, plan_code, status)
values
  ('11111111-1111-1111-1111-111111111111', 'pro', 'active'),
  ('22222222-2222-2222-2222-222222222222', 'enterprise', 'active')
on conflict (organization_id) do nothing;

insert into public.organization_memberships (organization_id, user_id, role, status)
values
  ('11111111-1111-1111-1111-111111111111', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'owner', 'active'),
  ('11111111-1111-1111-1111-111111111111', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'employee', 'active'),
  ('22222222-2222-2222-2222-222222222222', 'cccccccc-cccc-cccc-cccc-cccccccccccc', 'owner', 'active')
on conflict (organization_id, user_id) do nothing;

-- ---------------------------------------------------------------------------
-- Demo departments & employees
-- ---------------------------------------------------------------------------
insert into public.departments (id, organization_id, name, code, status)
values
  (
    'd1111111-1111-1111-1111-111111111111',
    '11111111-1111-1111-1111-111111111111',
    'Operations',
    'OPS',
    'active'
  ),
  (
    'd1111111-1111-1111-1111-111111111112',
    '11111111-1111-1111-1111-111111111111',
    'Procurement',
    'PROC',
    'active'
  ),
  (
    'd2222222-2222-2222-2222-222222222221',
    '22222222-2222-2222-2222-222222222222',
    'Finance',
    'FIN',
    'active'
  )
on conflict (id) do nothing;

insert into public.employees (
  id, organization_id, user_id, employee_code, full_name, email, title, department_id, status
)
values
  (
    'e1111111-1111-1111-1111-111111111111',
    '11111111-1111-1111-1111-111111111111',
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    'E-001',
    'Alex Owner',
    'owner@demo.bpm.local',
    'Organization Owner',
    'd1111111-1111-1111-1111-111111111111',
    'active'
  ),
  (
    'e1111111-1111-1111-1111-111111111112',
    '11111111-1111-1111-1111-111111111111',
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
    'E-002',
    'Sam Employee',
    'employee@demo.bpm.local',
    'Procurement Specialist',
    'd1111111-1111-1111-1111-111111111112',
    'active'
  ),
  (
    'e2222222-2222-2222-2222-222222222221',
    '22222222-2222-2222-2222-222222222222',
    'cccccccc-cccc-cccc-cccc-cccccccccccc',
    'E-101',
    'Jordan Other',
    'owner@other.bpm.local',
    'Finance Lead',
    'd2222222-2222-2222-2222-222222222221',
    'active'
  )
on conflict (id) do nothing;

update public.departments
set manager_employee_id = 'e1111111-1111-1111-1111-111111111111'
where id = 'd1111111-1111-1111-1111-111111111111';

insert into public.employee_manager_links (
  organization_id, employee_id, manager_employee_id, link_type, status
)
values (
  '11111111-1111-1111-1111-111111111111',
  'e1111111-1111-1111-1111-111111111112',
  'e1111111-1111-1111-1111-111111111111',
  'direct',
  'active'
)
on conflict do nothing;

-- ---------------------------------------------------------------------------
-- Demo suppliers
-- ---------------------------------------------------------------------------
insert into public.suppliers (id, organization_id, name, code, status, country_code)
values
  (
    's1111111-1111-1111-1111-111111111111',
    '11111111-1111-1111-1111-111111111111',
    'Northwind Supplies',
    'NW-01',
    'active',
    'US'
  ),
  (
    's1111111-1111-1111-1111-111111111112',
    '11111111-1111-1111-1111-111111111111',
    'Contoso Components',
    'CC-02',
    'active',
    'US'
  ),
  (
    's2222222-2222-2222-2222-222222222221',
    '22222222-2222-2222-2222-222222222222',
    'Other Org Vendor',
    'OV-01',
    'active',
    'GB'
  )
on conflict (id) do nothing;

insert into public.supplier_contacts (
  organization_id, supplier_id, full_name, email, is_primary, status
)
select
  '11111111-1111-1111-1111-111111111111',
  's1111111-1111-1111-1111-111111111111',
  'Casey Contact',
  'casey@northwind.example',
  true,
  'active'
where not exists (
  select 1
  from public.supplier_contacts sc
  where sc.supplier_id = 's1111111-1111-1111-1111-111111111111'
    and sc.email = 'casey@northwind.example'
);

insert into public.supplier_products (
  organization_id, supplier_id, sku, name, unit_of_measure, unit_price, currency_code, status
)
values (
  '11111111-1111-1111-1111-111111111111',
  's1111111-1111-1111-1111-111111111111',
  'NW-LAP-14',
  '14-inch Laptop',
  'each',
  1200.0000,
  'USD',
  'active'
)
on conflict (organization_id, supplier_id, sku) do nothing;

-- ---------------------------------------------------------------------------
-- Demo policy documents
-- ---------------------------------------------------------------------------
insert into public.policies (id, organization_id, code, title, category, status)
values (
  'p1111111-1111-1111-1111-111111111111',
  '11111111-1111-1111-1111-111111111111',
  'PROC-001',
  'Procurement Approval Policy',
  'procurement',
  'active'
)
on conflict (id) do nothing;

insert into public.policy_versions (
  id, organization_id, policy_id, version_number, body_text, body_hash, status, created_by_user_id
)
values (
  'pv111111-1111-1111-1111-111111111111',
  '11111111-1111-1111-1111-111111111111',
  'p1111111-1111-1111-1111-111111111111',
  1,
  'Purchases above 5000 USD require manager approval. Purchases above 25000 USD require owner approval.',
  encode(digest('Purchases above 5000 USD require manager approval. Purchases above 25000 USD require owner approval.', 'sha256'), 'hex'),
  'published',
  'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
)
on conflict (id) do nothing;

update public.policies
set current_version_id = 'pv111111-1111-1111-1111-111111111111'
where id = 'p1111111-1111-1111-1111-111111111111';

insert into public.documents (
  id,
  organization_id,
  title,
  document_type,
  storage_bucket,
  storage_path,
  mime_type,
  status,
  uploaded_by_user_id,
  source_policy_id
)
values
  (
    'doc11111-1111-1111-1111-111111111111',
    '11111111-1111-1111-1111-111111111111',
    'Procurement Approval Policy PDF',
    'policy',
    'documents',
    '11111111-1111-1111-1111-111111111111/policies/proc-001.pdf',
    'application/pdf',
    'indexed',
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    'p1111111-1111-1111-1111-111111111111'
  ),
  (
    'doc22222-2222-2222-2222-222222222221',
    '22222222-2222-2222-2222-222222222222',
    'Other Org Confidential Policy',
    'policy',
    'documents',
    '22222222-2222-2222-2222-222222222222/policies/other.pdf',
    'application/pdf',
    'indexed',
    'cccccccc-cccc-cccc-cccc-cccccccccccc',
    null
  )
on conflict (id) do nothing;

insert into public.document_chunks (
  id, organization_id, document_id, chunk_index, content, metadata
)
values (
  'chunk111-1111-1111-1111-111111111111',
  '11111111-1111-1111-1111-111111111111',
  'doc11111-1111-1111-1111-111111111111',
  0,
  'Purchases above 5000 USD require manager approval.',
  '{"source":"seed"}'::jsonb
)
on conflict (id) do nothing;

insert into public.audit_logs (
  organization_id, actor_user_id, actor_type, action, resource_type, resource_id, payload
)
select
  '11111111-1111-1111-1111-111111111111',
  'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  'user',
  'seed.completed',
  'organization',
  '11111111-1111-1111-1111-111111111111',
  '{"note":"demo seed applied"}'::jsonb
where not exists (
  select 1
  from public.audit_logs a
  where a.organization_id = '11111111-1111-1111-1111-111111111111'
    and a.action = 'seed.completed'
);
