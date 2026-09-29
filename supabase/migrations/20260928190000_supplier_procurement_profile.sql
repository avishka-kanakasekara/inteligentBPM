-- Procurement profile for suppliers: evaluation, contracts, risk, and
-- future supplier recommendation.
-- Existing rows keep their name, code, website, country, and approval status.

alter table public.suppliers
  add column if not exists supplier_number text,
  add column if not exists city text,
  add column if not exists address text,
  add column if not exists business_registration_number text,
  add column if not exists tax_number text,
  add column if not exists primary_contact_name text,
  add column if not exists primary_contact_email text,
  add column if not exists primary_contact_phone text,
  add column if not exists secondary_contact_name text,
  add column if not exists secondary_contact_email text,
  add column if not exists secondary_contact_phone text,
  add column if not exists supplier_category text not null default 'other',
  add column if not exists products_services text,
  add column if not exists lead_time_days integer,
  add column if not exists minimum_order_quantity numeric(18, 2),
  add column if not exists payment_terms text,
  add column if not exists preferred_currency text not null default 'USD',
  add column if not exists risk_level text not null default 'low',
  add column if not exists compliance_status text not null default 'pending',
  add column if not exists insurance_valid boolean not null default false,
  add column if not exists contract_start_date date,
  add column if not exists contract_expiry_date date,
  add column if not exists certification_details text,
  add column if not exists supplier_rating numeric(3, 2),
  add column if not exists on_time_delivery_percent numeric(5, 2),
  add column if not exists quality_score_percent numeric(5, 2),
  add column if not exists average_response_hours numeric(8, 2),
  add column if not exists rejected_orders_count integer not null default 0,
  add column if not exists total_orders_completed integer not null default 0,
  add column if not exists approval_tier text not null default 'none',
  add column if not exists preferred_supplier boolean not null default false,
  add column if not exists blacklisted boolean not null default false,
  add column if not exists suspension_reason text,
  add column if not exists notes text;

update public.suppliers
set supplier_number = 'SUP-' || upper(substr(replace(id::text, '-', ''), 1, 8))
where supplier_number is null;

create unique index if not exists suppliers_org_supplier_number_unique
  on public.suppliers (organization_id, supplier_number)
  where supplier_number is not null;

alter table public.suppliers drop constraint if exists suppliers_category_check;
alter table public.suppliers
  add constraint suppliers_category_check
  check (
    supplier_category in (
      'raw_materials', 'manufacturing', 'logistics', 'it_services',
      'consulting', 'finance', 'other'
    )
  );

alter table public.suppliers drop constraint if exists suppliers_risk_level_check;
alter table public.suppliers
  add constraint suppliers_risk_level_check
  check (risk_level in ('low', 'medium', 'high'));

alter table public.suppliers drop constraint if exists suppliers_compliance_status_check;
alter table public.suppliers
  add constraint suppliers_compliance_status_check
  check (compliance_status in ('pending', 'compliant', 'non_compliant', 'expired'));

alter table public.suppliers drop constraint if exists suppliers_approval_tier_check;
alter table public.suppliers
  add constraint suppliers_approval_tier_check
  check (approval_tier in ('none', 'team', 'department', 'business_unit', 'executive'));

alter table public.suppliers drop constraint if exists suppliers_rating_check;
alter table public.suppliers
  add constraint suppliers_rating_check
  check (supplier_rating is null or (supplier_rating >= 1 and supplier_rating <= 5));

alter table public.suppliers drop constraint if exists suppliers_on_time_check;
alter table public.suppliers
  add constraint suppliers_on_time_check
  check (
    on_time_delivery_percent is null
    or (on_time_delivery_percent >= 0 and on_time_delivery_percent <= 100)
  );

alter table public.suppliers drop constraint if exists suppliers_quality_check;
alter table public.suppliers
  add constraint suppliers_quality_check
  check (
    quality_score_percent is null
    or (quality_score_percent >= 0 and quality_score_percent <= 100)
  );

alter table public.suppliers drop constraint if exists suppliers_rejected_orders_check;
alter table public.suppliers
  add constraint suppliers_rejected_orders_check
  check (rejected_orders_count >= 0);

alter table public.suppliers drop constraint if exists suppliers_completed_orders_check;
alter table public.suppliers
  add constraint suppliers_completed_orders_check
  check (total_orders_completed >= 0);

alter table public.suppliers drop constraint if exists suppliers_contract_dates_check;
alter table public.suppliers
  add constraint suppliers_contract_dates_check
  check (
    contract_start_date is null
    or contract_expiry_date is null
    or contract_expiry_date >= contract_start_date
  );

create index if not exists suppliers_category_idx
  on public.suppliers (organization_id, supplier_category);
create index if not exists suppliers_risk_level_idx
  on public.suppliers (organization_id, risk_level);
