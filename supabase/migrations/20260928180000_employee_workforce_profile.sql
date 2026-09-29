-- Workforce profile for employees: planning, allocation, approvals, and
-- future AI resource recommendations.
-- Existing rows keep their identity and receive safe defaults.

alter table public.employees
  add column if not exists phone text,
  add column if not exists employment_type text not null default 'full_time',
  add column if not exists join_date date,
  add column if not exists manager_employee_id uuid,
  add column if not exists team text,
  add column if not exists business_unit text,
  add column if not exists location text,
  add column if not exists reporting_level integer not null default 1,
  add column if not exists primary_skills jsonb not null default '[]'::jsonb,
  add column if not exists secondary_skills jsonb not null default '[]'::jsonb,
  add column if not exists certifications jsonb not null default '[]'::jsonb,
  add column if not exists years_of_experience numeric(5, 1),
  add column if not exists skill_level text not null default 'intermediate',
  add column if not exists availability_percent numeric(5, 2) not null default 100,
  add column if not exists weekly_capacity_hours numeric(6, 2) not null default 40,
  add column if not exists current_workload_percent numeric(5, 2) not null default 0,
  add column if not exists cost_per_hour numeric(18, 2),
  add column if not exists monthly_cost numeric(18, 2),
  add column if not exists max_allocation_percent numeric(5, 2) not null default 100,
  add column if not exists approval_tier text not null default 'none',
  add column if not exists can_approve_procurement boolean not null default false,
  add column if not exists can_approve_budget boolean not null default false,
  add column if not exists delegation_authority boolean not null default false,
  add column if not exists tasks_completed integer,
  add column if not exists avg_task_completion_hours numeric(8, 2),
  add column if not exists sla_compliance_percent numeric(5, 2),
  add column if not exists performance_score numeric(5, 2);

-- Backfill a stable employee id only where one was never assigned.
update public.employees
set employee_code = 'EMP-' || upper(substr(replace(id::text, '-', ''), 1, 8))
where employee_code is null;

alter table public.employees
  drop constraint if exists employees_employment_type_check;
alter table public.employees
  add constraint employees_employment_type_check
  check (employment_type in ('full_time', 'part_time', 'contract'));

alter table public.employees
  drop constraint if exists employees_skill_level_check;
alter table public.employees
  add constraint employees_skill_level_check
  check (skill_level in ('beginner', 'intermediate', 'expert'));

alter table public.employees
  drop constraint if exists employees_approval_tier_check;
alter table public.employees
  add constraint employees_approval_tier_check
  check (approval_tier in ('none', 'team', 'department', 'business_unit', 'executive'));

alter table public.employees
  drop constraint if exists employees_reporting_level_check;
alter table public.employees
  add constraint employees_reporting_level_check
  check (reporting_level >= 1);

alter table public.employees
  drop constraint if exists employees_availability_percent_check;
alter table public.employees
  add constraint employees_availability_percent_check
  check (availability_percent >= 0 and availability_percent <= 100);

alter table public.employees
  drop constraint if exists employees_workload_percent_check;
alter table public.employees
  add constraint employees_workload_percent_check
  check (current_workload_percent >= 0 and current_workload_percent <= 100);

alter table public.employees
  drop constraint if exists employees_max_allocation_percent_check;
alter table public.employees
  add constraint employees_max_allocation_percent_check
  check (max_allocation_percent >= 0 and max_allocation_percent <= 100);

alter table public.employees
  drop constraint if exists employees_weekly_capacity_check;
alter table public.employees
  add constraint employees_weekly_capacity_check
  check (weekly_capacity_hours >= 0 and weekly_capacity_hours <= 168);

alter table public.employees
  drop constraint if exists employees_manager_self_check;
alter table public.employees
  add constraint employees_manager_self_check
  check (manager_employee_id is null or manager_employee_id <> id);

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'employees_manager_employee_id_fkey'
  ) then
    alter table public.employees
      add constraint employees_manager_employee_id_fkey
      foreign key (manager_employee_id)
      references public.employees (id)
      on delete set null;
  end if;
end $$;

create index if not exists employees_manager_employee_id_idx
  on public.employees (manager_employee_id);
create index if not exists employees_employment_type_idx
  on public.employees (organization_id, employment_type);
create index if not exists employees_primary_skills_idx
  on public.employees using gin (primary_skills);
