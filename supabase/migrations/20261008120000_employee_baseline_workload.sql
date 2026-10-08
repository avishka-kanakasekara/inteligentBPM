-- Manual starting workload. current_workload_percent remains the calculated total.
-- Existing typed values become the baseline before any calculated updates.

alter table public.employees
  add column if not exists baseline_workload_percent numeric(5, 2);

update public.employees
set baseline_workload_percent = current_workload_percent
where baseline_workload_percent is null;

alter table public.employees
  alter column baseline_workload_percent set default 0;

alter table public.employees
  alter column baseline_workload_percent set not null;

alter table public.employees
  drop constraint if exists employees_baseline_workload_percent_check;

alter table public.employees
  add constraint employees_baseline_workload_percent_check
  check (baseline_workload_percent >= 0 and baseline_workload_percent <= 100);
