-- Row Level Security for every exposed tenant table.
-- Anonymous users get no tenant access. Authenticated access requires active membership.
-- Service role used by the backend bypasses RLS (Supabase default) and must still
-- enforce organization_id in application code.

-- Grants: table access is gated by RLS.
grant usage on schema public to anon, authenticated;

grant select, insert, update, delete on all tables in schema public to authenticated;
grant select on all tables in schema public to anon;
grant usage, select on all sequences in schema public to authenticated;

alter default privileges in schema public
  grant select, insert, update, delete on tables to authenticated;
alter default privileges in schema public
  grant select on tables to anon;

-- ---------------------------------------------------------------------------
-- Enable RLS
-- ---------------------------------------------------------------------------
alter table public.organizations enable row level security;
alter table public.organization_settings enable row level security;
alter table public.organization_memberships enable row level security;
alter table public.employees enable row level security;
alter table public.employee_manager_links enable row level security;
alter table public.departments enable row level security;
alter table public.suppliers enable row level security;
alter table public.supplier_contacts enable row level security;
alter table public.supplier_products enable row level security;
alter table public.budgets enable row level security;
alter table public.policies enable row level security;
alter table public.policy_versions enable row level security;
alter table public.documents enable row level security;
alter table public.document_chunks enable row level security;
alter table public.process_definitions enable row level security;
alter table public.process_versions enable row level security;
alter table public.process_steps enable row level security;
alter table public.process_edges enable row level security;
alter table public.process_runs enable row level security;
alter table public.process_step_runs enable row level security;
alter table public.agent_runs enable row level security;
alter table public.agent_messages enable row level security;
alter table public.approvals enable row level security;
alter table public.tool_calls enable row level security;
alter table public.integration_connections enable row level security;
alter table public.quotations enable row level security;
alter table public.quotation_items enable row level security;
alter table public.purchase_orders enable row level security;
alter table public.notifications enable row level security;
alter table public.audit_logs enable row level security;
alter table public.subscriptions enable row level security;
alter table public.plan_entitlements enable row level security;
alter table public.usage_events enable row level security;
alter table public.idempotency_keys enable row level security;
alter table public.outbox_events enable row level security;
alter table public.inbox_events enable row level security;

-- Force RLS for table owners as well (defense in depth on Supabase).
alter table public.organizations force row level security;
alter table public.organization_settings force row level security;
alter table public.organization_memberships force row level security;
alter table public.employees force row level security;
alter table public.employee_manager_links force row level security;
alter table public.departments force row level security;
alter table public.suppliers force row level security;
alter table public.supplier_contacts force row level security;
alter table public.supplier_products force row level security;
alter table public.budgets force row level security;
alter table public.policies force row level security;
alter table public.policy_versions force row level security;
alter table public.documents force row level security;
alter table public.document_chunks force row level security;
alter table public.process_definitions force row level security;
alter table public.process_versions force row level security;
alter table public.process_steps force row level security;
alter table public.process_edges force row level security;
alter table public.process_runs force row level security;
alter table public.process_step_runs force row level security;
alter table public.agent_runs force row level security;
alter table public.agent_messages force row level security;
alter table public.approvals force row level security;
alter table public.tool_calls force row level security;
alter table public.integration_connections force row level security;
alter table public.quotations force row level security;
alter table public.quotation_items force row level security;
alter table public.purchase_orders force row level security;
alter table public.notifications force row level security;
alter table public.audit_logs force row level security;
alter table public.subscriptions force row level security;
alter table public.plan_entitlements force row level security;
alter table public.usage_events force row level security;
alter table public.idempotency_keys force row level security;
alter table public.outbox_events force row level security;
alter table public.inbox_events force row level security;

-- ---------------------------------------------------------------------------
-- organizations
-- ---------------------------------------------------------------------------
create policy organizations_select_member
  on public.organizations for select to authenticated
  using (public.is_org_member(id));

create policy organizations_insert_authenticated
  on public.organizations for insert to authenticated
  with check (auth.uid() is not null);

create policy organizations_update_admin
  on public.organizations for update to authenticated
  using (public.is_org_admin(id))
  with check (public.is_org_admin(id));

-- ---------------------------------------------------------------------------
-- organization_settings
-- ---------------------------------------------------------------------------
create policy organization_settings_select_member
  on public.organization_settings for select to authenticated
  using (public.is_org_member(organization_id));

create policy organization_settings_insert_admin
  on public.organization_settings for insert to authenticated
  with check (public.is_org_admin(organization_id));

create policy organization_settings_update_admin
  on public.organization_settings for update to authenticated
  using (public.is_org_admin(organization_id))
  with check (public.is_org_admin(organization_id));

-- ---------------------------------------------------------------------------
-- organization_memberships
-- ---------------------------------------------------------------------------
create policy memberships_select_member
  on public.organization_memberships for select to authenticated
  using (
    public.is_org_member(organization_id)
    or user_id = auth.uid()
  );

create policy memberships_insert_admin
  on public.organization_memberships for insert to authenticated
  with check (
    public.is_org_admin(organization_id)
    or (
      -- Bootstrap: first owner membership for an org the user just created
      role = 'owner'
      and user_id = auth.uid()
      and status = 'active'
    )
  );

create policy memberships_update_admin
  on public.organization_memberships for update to authenticated
  using (public.is_org_admin(organization_id))
  with check (public.is_org_admin(organization_id));

-- ---------------------------------------------------------------------------
-- Helper macro pattern: member read / admin-or-manager write for directory
-- ---------------------------------------------------------------------------
create policy employees_select_member
  on public.employees for select to authenticated
  using (public.is_org_member(organization_id));

create policy employees_insert_manager
  on public.employees for insert to authenticated
  with check (public.can_manage_directory(organization_id));

create policy employees_update_manager
  on public.employees for update to authenticated
  using (public.can_manage_directory(organization_id))
  with check (public.can_manage_directory(organization_id));

create policy employees_delete_admin
  on public.employees for delete to authenticated
  using (public.is_org_admin(organization_id));

create policy employee_manager_links_select_member
  on public.employee_manager_links for select to authenticated
  using (public.is_org_member(organization_id));

create policy employee_manager_links_write_manager
  on public.employee_manager_links for insert to authenticated
  with check (public.can_manage_directory(organization_id));

create policy employee_manager_links_update_manager
  on public.employee_manager_links for update to authenticated
  using (public.can_manage_directory(organization_id))
  with check (public.can_manage_directory(organization_id));

create policy employee_manager_links_delete_admin
  on public.employee_manager_links for delete to authenticated
  using (public.is_org_admin(organization_id));

create policy departments_select_member
  on public.departments for select to authenticated
  using (public.is_org_member(organization_id));

create policy departments_insert_manager
  on public.departments for insert to authenticated
  with check (public.can_manage_directory(organization_id));

create policy departments_update_manager
  on public.departments for update to authenticated
  using (public.can_manage_directory(organization_id))
  with check (public.can_manage_directory(organization_id));

create policy departments_delete_admin
  on public.departments for delete to authenticated
  using (public.is_org_admin(organization_id));

create policy suppliers_select_member
  on public.suppliers for select to authenticated
  using (public.is_org_member(organization_id));

create policy suppliers_insert_manager
  on public.suppliers for insert to authenticated
  with check (public.can_manage_directory(organization_id));

create policy suppliers_update_manager
  on public.suppliers for update to authenticated
  using (public.can_manage_directory(organization_id))
  with check (public.can_manage_directory(organization_id));

create policy suppliers_delete_admin
  on public.suppliers for delete to authenticated
  using (public.is_org_admin(organization_id));

create policy supplier_contacts_select_member
  on public.supplier_contacts for select to authenticated
  using (public.is_org_member(organization_id));

create policy supplier_contacts_write_manager
  on public.supplier_contacts for all to authenticated
  using (public.can_manage_directory(organization_id))
  with check (public.can_manage_directory(organization_id));

create policy supplier_products_select_member
  on public.supplier_products for select to authenticated
  using (public.is_org_member(organization_id));

create policy supplier_products_write_manager
  on public.supplier_products for all to authenticated
  using (public.can_manage_directory(organization_id))
  with check (public.can_manage_directory(organization_id));

create policy budgets_select_member
  on public.budgets for select to authenticated
  using (public.is_org_member(organization_id));

create policy budgets_write_admin
  on public.budgets for all to authenticated
  using (public.is_org_admin(organization_id))
  with check (public.is_org_admin(organization_id));

-- Policies / documents
create policy policies_select_member
  on public.policies for select to authenticated
  using (public.is_org_member(organization_id));

create policy policies_write_compliance
  on public.policies for all to authenticated
  using (public.can_manage_policies(organization_id))
  with check (public.can_manage_policies(organization_id));

create policy policy_versions_select_member
  on public.policy_versions for select to authenticated
  using (public.is_org_member(organization_id));

create policy policy_versions_write_compliance
  on public.policy_versions for all to authenticated
  using (public.can_manage_policies(organization_id))
  with check (public.can_manage_policies(organization_id));

create policy documents_select_member
  on public.documents for select to authenticated
  using (public.is_org_member(organization_id));

create policy documents_insert_member
  on public.documents for insert to authenticated
  with check (public.is_org_member(organization_id));

create policy documents_update_member
  on public.documents for update to authenticated
  using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

create policy documents_delete_admin
  on public.documents for delete to authenticated
  using (public.is_org_admin(organization_id));

create policy document_chunks_select_member
  on public.document_chunks for select to authenticated
  using (public.is_org_member(organization_id));

create policy document_chunks_write_member
  on public.document_chunks for insert to authenticated
  with check (public.is_org_member(organization_id));

create policy document_chunks_update_member
  on public.document_chunks for update to authenticated
  using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

create policy document_chunks_delete_admin
  on public.document_chunks for delete to authenticated
  using (public.is_org_admin(organization_id));

-- Processes
create policy process_definitions_select_member
  on public.process_definitions for select to authenticated
  using (public.is_org_member(organization_id));

create policy process_definitions_insert_member
  on public.process_definitions for insert to authenticated
  with check (public.is_org_member(organization_id));

create policy process_definitions_update_member
  on public.process_definitions for update to authenticated
  using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

create policy process_versions_select_member
  on public.process_versions for select to authenticated
  using (public.is_org_member(organization_id));

create policy process_versions_insert_member
  on public.process_versions for insert to authenticated
  with check (public.is_org_member(organization_id));

create policy process_versions_update_member
  on public.process_versions for update to authenticated
  using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

create policy process_steps_select_member
  on public.process_steps for select to authenticated
  using (public.is_org_member(organization_id));

create policy process_steps_write_member
  on public.process_steps for all to authenticated
  using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

create policy process_edges_select_member
  on public.process_edges for select to authenticated
  using (public.is_org_member(organization_id));

create policy process_edges_write_member
  on public.process_edges for all to authenticated
  using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

create policy process_runs_select_member
  on public.process_runs for select to authenticated
  using (public.is_org_member(organization_id));

create policy process_runs_insert_member
  on public.process_runs for insert to authenticated
  with check (public.is_org_member(organization_id));

create policy process_runs_update_member
  on public.process_runs for update to authenticated
  using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

create policy process_step_runs_select_member
  on public.process_step_runs for select to authenticated
  using (public.is_org_member(organization_id));

create policy process_step_runs_write_member
  on public.process_step_runs for all to authenticated
  using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

create policy agent_runs_select_member
  on public.agent_runs for select to authenticated
  using (public.is_org_member(organization_id));

create policy agent_runs_write_member
  on public.agent_runs for all to authenticated
  using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

create policy agent_messages_select_member
  on public.agent_messages for select to authenticated
  using (public.is_org_member(organization_id));

create policy agent_messages_write_member
  on public.agent_messages for all to authenticated
  using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

-- Approvals: membership required; decisions restricted by role
create policy approvals_select_member
  on public.approvals for select to authenticated
  using (public.is_org_member(organization_id));

create policy approvals_insert_member
  on public.approvals for insert to authenticated
  with check (public.is_org_member(organization_id));

create policy approvals_update_deciders
  on public.approvals for update to authenticated
  using (public.can_decide_approvals(organization_id))
  with check (public.can_decide_approvals(organization_id));

create policy tool_calls_select_member
  on public.tool_calls for select to authenticated
  using (public.is_org_member(organization_id));

create policy tool_calls_write_member
  on public.tool_calls for all to authenticated
  using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

create policy integration_connections_select_admin
  on public.integration_connections for select to authenticated
  using (public.can_configure_integrations(organization_id));

create policy integration_connections_write_admin
  on public.integration_connections for all to authenticated
  using (public.can_configure_integrations(organization_id))
  with check (public.can_configure_integrations(organization_id));

create policy quotations_select_member
  on public.quotations for select to authenticated
  using (public.is_org_member(organization_id));

create policy quotations_write_member
  on public.quotations for all to authenticated
  using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

create policy quotation_items_select_member
  on public.quotation_items for select to authenticated
  using (public.is_org_member(organization_id));

create policy quotation_items_write_member
  on public.quotation_items for all to authenticated
  using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

create policy purchase_orders_select_member
  on public.purchase_orders for select to authenticated
  using (public.is_org_member(organization_id));

create policy purchase_orders_write_member
  on public.purchase_orders for all to authenticated
  using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

-- Notifications: own rows within org membership
create policy notifications_select_own
  on public.notifications for select to authenticated
  using (
    public.is_org_member(organization_id)
    and user_id = auth.uid()
  );

create policy notifications_update_own
  on public.notifications for update to authenticated
  using (
    public.is_org_member(organization_id)
    and user_id = auth.uid()
  )
  with check (
    public.is_org_member(organization_id)
    and user_id = auth.uid()
  );

create policy notifications_insert_member
  on public.notifications for insert to authenticated
  with check (public.is_org_member(organization_id));

-- Audit logs: authorized read; insert by members/system path; no update/delete via RLS
create policy audit_logs_select_authorized
  on public.audit_logs for select to authenticated
  using (public.can_read_audit(organization_id));

create policy audit_logs_insert_member
  on public.audit_logs for insert to authenticated
  with check (public.is_org_member(organization_id));

-- No UPDATE/DELETE policies on audit_logs for authenticated/anon.
-- Triggers also deny mutation.

-- Billing
create policy subscriptions_select_billing
  on public.subscriptions for select to authenticated
  using (public.can_manage_billing(organization_id));

create policy subscriptions_write_billing
  on public.subscriptions for all to authenticated
  using (public.can_manage_billing(organization_id))
  with check (public.can_manage_billing(organization_id));

create policy usage_events_select_billing
  on public.usage_events for select to authenticated
  using (
    public.can_manage_billing(organization_id)
    or public.can_read_audit(organization_id)
  );

create policy usage_events_insert_admin
  on public.usage_events for insert to authenticated
  with check (public.can_manage_billing(organization_id));

-- Plan catalog: readable by authenticated users; writes via service role only
create policy plan_entitlements_select_authenticated
  on public.plan_entitlements for select to authenticated
  using (true);

-- Idempotency / outbox / inbox: members can read own org; writes typically service role
create policy idempotency_keys_select_member
  on public.idempotency_keys for select to authenticated
  using (public.is_org_member(organization_id));

create policy idempotency_keys_write_member
  on public.idempotency_keys for all to authenticated
  using (public.is_org_member(organization_id))
  with check (public.is_org_member(organization_id));

create policy outbox_events_select_admin
  on public.outbox_events for select to authenticated
  using (public.is_org_admin(organization_id));

create policy outbox_events_write_admin
  on public.outbox_events for all to authenticated
  using (public.is_org_admin(organization_id))
  with check (public.is_org_admin(organization_id));

create policy inbox_events_select_admin
  on public.inbox_events for select to authenticated
  using (public.is_org_admin(organization_id));

create policy inbox_events_write_admin
  on public.inbox_events for all to authenticated
  using (public.is_org_admin(organization_id))
  with check (public.is_org_admin(organization_id));
