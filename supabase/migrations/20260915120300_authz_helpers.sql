-- Membership/authorization helpers used by RLS policies.
-- Created after organization_memberships exists.

create or replace function public.current_user_id()
returns uuid
language sql
stable
as $$
  select auth.uid();
$$;

create or replace function public.is_org_member(p_organization_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.organization_memberships m
    where m.organization_id = p_organization_id
      and m.user_id = auth.uid()
      and m.status = 'active'
  );
$$;

create or replace function public.has_org_role(p_organization_id uuid, p_roles text[])
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.organization_memberships m
    where m.organization_id = p_organization_id
      and m.user_id = auth.uid()
      and m.status = 'active'
      and m.role = any (p_roles)
  );
$$;

create or replace function public.is_org_admin(p_organization_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select public.has_org_role(p_organization_id, array['owner', 'admin']);
$$;

create or replace function public.can_manage_directory(p_organization_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select public.has_org_role(p_organization_id, array['owner', 'admin', 'manager']);
$$;

create or replace function public.can_decide_approvals(p_organization_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select public.has_org_role(
    p_organization_id,
    array['owner', 'admin', 'manager', 'compliance']
  );
$$;

create or replace function public.can_read_audit(p_organization_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select public.has_org_role(
    p_organization_id,
    array['owner', 'admin', 'compliance', 'auditor']
  );
$$;

create or replace function public.can_manage_billing(p_organization_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select public.has_org_role(p_organization_id, array['owner', 'admin']);
$$;

create or replace function public.can_configure_integrations(p_organization_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select public.has_org_role(p_organization_id, array['owner', 'admin']);
$$;

create or replace function public.can_manage_policies(p_organization_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select public.has_org_role(
    p_organization_id,
    array['owner', 'admin', 'compliance']
  );
$$;

revoke all on function public.is_org_member(uuid) from public;
revoke all on function public.has_org_role(uuid, text[]) from public;
revoke all on function public.is_org_admin(uuid) from public;
revoke all on function public.can_manage_directory(uuid) from public;
revoke all on function public.can_decide_approvals(uuid) from public;
revoke all on function public.can_read_audit(uuid) from public;
revoke all on function public.can_manage_billing(uuid) from public;
revoke all on function public.can_configure_integrations(uuid) from public;
revoke all on function public.can_manage_policies(uuid) from public;

grant execute on function public.current_user_id() to authenticated, anon;
grant execute on function public.is_org_member(uuid) to authenticated, anon;
grant execute on function public.has_org_role(uuid, text[]) to authenticated, anon;
grant execute on function public.is_org_admin(uuid) to authenticated, anon;
grant execute on function public.can_manage_directory(uuid) to authenticated, anon;
grant execute on function public.can_decide_approvals(uuid) to authenticated, anon;
grant execute on function public.can_read_audit(uuid) to authenticated, anon;
grant execute on function public.can_manage_billing(uuid) to authenticated, anon;
grant execute on function public.can_configure_integrations(uuid) to authenticated, anon;
grant execute on function public.can_manage_policies(uuid) to authenticated, anon;
