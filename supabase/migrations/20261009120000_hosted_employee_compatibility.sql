-- Additive compatibility for the hosted employees table.
-- Run this file as one transaction. A duplicate-code error rolls back
-- every change in the script. Do not commit before the checks below.
-- Keeps tenant_id, employee_number, and role_id. Does not add
-- organization_id, role_code, or approval_level.

alter table public.employees
  add column if not exists employee_code text;

-- Abort before copying when the resulting codes would collide in a tenant.
do $$
begin
  if exists (
    select 1
    from (
      select
        tenant_id,
        coalesce(employee_code, employee_number) as next_code
      from public.employees
    ) planned
    where next_code is not null
    group by tenant_id, next_code
    having count(*) > 1
  ) then
    raise exception
      'Duplicate employee_code values exist within a tenant. '
      'Migration stopped without inventing replacement codes.';
  end if;
end $$;

update public.employees
set employee_code = employee_number
where employee_code is null
  and employee_number is not null;

alter table public.employees
  add column if not exists primary_skills jsonb not null default '[]'::jsonb,
  add column if not exists secondary_skills jsonb not null default '[]'::jsonb,
  add column if not exists skill_level text not null default 'intermediate',
  add column if not exists availability_percent numeric(5, 2) not null default 100,
  add column if not exists weekly_capacity_hours numeric(8, 2) not null default 40,
  add column if not exists current_workload_percent numeric(5, 2) not null default 0,
  add column if not exists max_allocation_percent numeric(5, 2) not null default 100,
  add column if not exists cost_per_hour numeric(12, 2) not null default 0,
  add column if not exists approval_authority_limit numeric(12, 2),
  add column if not exists approval_tier text not null default 'none',
  add column if not exists is_manager boolean not null default false,
  add column if not exists employment_type text not null default 'full_time',
  add column if not exists reporting_level integer not null default 1;

alter table public.employees
  add column if not exists baseline_workload_percent numeric(5, 2);

update public.employees
set baseline_workload_percent = current_workload_percent
where baseline_workload_percent is null;

alter table public.employees
  alter column baseline_workload_percent set default 0;

alter table public.employees
  alter column baseline_workload_percent set not null;

-- Refuse to invent codes when one tenant already has duplicate identifiers.
do $$
begin
  if exists (
    select 1
    from public.employees
    where employee_code is not null
    group by tenant_id, employee_code
    having count(*) > 1
  ) then
    raise exception
      'Duplicate employee_code values exist within a tenant. '
      'Migration stopped without inventing replacement codes.';
  end if;
end $$;

create unique index if not exists employees_tenant_employee_code_unique
  on public.employees (tenant_id, employee_code);

alter table public.employees drop constraint if exists employees_skill_level_check;
alter table public.employees
  add constraint employees_skill_level_check
  check (skill_level in ('beginner', 'intermediate', 'expert'));

alter table public.employees drop constraint if exists employees_employment_type_check;
alter table public.employees
  add constraint employees_employment_type_check
  check (employment_type in ('full_time', 'part_time', 'contract'));

alter table public.employees drop constraint if exists employees_approval_tier_check;
alter table public.employees
  add constraint employees_approval_tier_check
  check (approval_tier in ('none', 'team', 'department', 'business_unit', 'executive'));

alter table public.employees drop constraint if exists employees_reporting_level_check;
alter table public.employees
  add constraint employees_reporting_level_check
  check (reporting_level >= 1);

alter table public.employees drop constraint if exists employees_availability_percent_check;
alter table public.employees
  add constraint employees_availability_percent_check
  check (availability_percent >= 0 and availability_percent <= 100);

alter table public.employees drop constraint if exists employees_weekly_capacity_check;
alter table public.employees
  add constraint employees_weekly_capacity_check
  check (weekly_capacity_hours >= 0 and weekly_capacity_hours <= 168);

alter table public.employees drop constraint if exists employees_workload_percent_check;
alter table public.employees
  add constraint employees_workload_percent_check
  check (current_workload_percent >= 0 and current_workload_percent <= 100);

alter table public.employees drop constraint if exists employees_baseline_workload_percent_check;
alter table public.employees
  add constraint employees_baseline_workload_percent_check
  check (baseline_workload_percent >= 0 and baseline_workload_percent <= 100);

alter table public.employees drop constraint if exists employees_max_allocation_percent_check;
alter table public.employees
  add constraint employees_max_allocation_percent_check
  check (max_allocation_percent >= 0 and max_allocation_percent <= 100);

alter table public.employees drop constraint if exists employees_cost_per_hour_check;
alter table public.employees
  add constraint employees_cost_per_hour_check
  check (cost_per_hour >= 0);

alter table public.employees drop constraint if exists employees_approval_authority_limit_check;
alter table public.employees
  add constraint employees_approval_authority_limit_check
  check (approval_authority_limit >= 0);

create index if not exists employees_primary_skills_idx
  on public.employees using gin (primary_skills);
