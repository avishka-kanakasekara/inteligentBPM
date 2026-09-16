-- Organization-scoped Storage for documents.
-- Paths must be: {organization_id}/... inside the documents bucket.
-- No local containers; configure against the hosted Supabase project.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'documents',
  'documents',
  false,
  52428800,
  array[
    'application/pdf',
    'text/plain',
    'text/markdown',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/msword'
  ]
)
on conflict (id) do update
set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

create or replace function public.storage_organization_id(object_name text)
returns uuid
language plpgsql
immutable
as $$
declare
  org_text text;
begin
  org_text := split_part(object_name, '/', 1);
  if org_text ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' then
    return org_text::uuid;
  end if;
  return null;
end;
$$;

grant execute on function public.storage_organization_id(text) to authenticated, anon;

drop policy if exists documents_storage_select on storage.objects;
drop policy if exists documents_storage_insert on storage.objects;
drop policy if exists documents_storage_update on storage.objects;
drop policy if exists documents_storage_delete on storage.objects;

create policy documents_storage_select
  on storage.objects for select to authenticated
  using (
    bucket_id = 'documents'
    and public.is_org_member(public.storage_organization_id(name))
  );

create policy documents_storage_insert
  on storage.objects for insert to authenticated
  with check (
    bucket_id = 'documents'
    and public.is_org_member(public.storage_organization_id(name))
  );

create policy documents_storage_update
  on storage.objects for update to authenticated
  using (
    bucket_id = 'documents'
    and public.is_org_member(public.storage_organization_id(name))
  )
  with check (
    bucket_id = 'documents'
    and public.is_org_member(public.storage_organization_id(name))
  );

create policy documents_storage_delete
  on storage.objects for delete to authenticated
  using (
    bucket_id = 'documents'
    and public.is_org_admin(public.storage_organization_id(name))
  );
