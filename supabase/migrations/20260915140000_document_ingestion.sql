-- Document ingestion metadata extensions for retrieval, citations, and access control.

alter table public.documents
  add column if not exists file_name text,
  add column if not exists version_number integer not null default 1 check (version_number > 0),
  add column if not exists source_type text not null default 'upload'
    check (source_type in ('upload', 'email_export', 'policy_attach', 'process_attach', 'import')),
  add column if not exists classification text not null default 'internal'
    check (classification in ('public', 'internal', 'confidential', 'restricted')),
  add column if not exists access_scope text not null default 'organization'
    check (access_scope in ('organization', 'department', 'owner', 'restricted')),
  add column if not exists owner_user_id uuid,
  add column if not exists created_by_user_id uuid,
  add column if not exists embedding_model text,
  add column if not exists embedding_dimension integer,
  add column if not exists page_count integer,
  add column if not exists section_count integer,
  add column if not exists chunk_count integer not null default 0,
  add column if not exists suspicious_flags jsonb not null default '[]'::jsonb,
  add column if not exists redacted boolean not null default false;

-- Align status check with full ingestion lifecycle (recreate constraint).
alter table public.documents drop constraint if exists documents_status_check;
alter table public.documents
  add constraint documents_status_check check (status in (
    'uploaded', 'queued', 'scanning', 'extracting', 'chunking',
    'embedding', 'indexed', 'failed', 'quarantined', 'archived'
  ));

-- Duplicate detection by checksum within an organization (active documents only).
create unique index if not exists documents_org_active_checksum_unique
  on public.documents (organization_id, content_hash)
  where content_hash is not null
    and status not in ('failed', 'quarantined', 'archived');

alter table public.document_chunks
  add column if not exists page_number integer,
  add column if not exists section_heading text,
  add column if not exists start_offset integer,
  add column if not exists end_offset integer,
  add column if not exists embedding_model text,
  add column if not exists is_redacted boolean not null default false,
  add column if not exists suspicious boolean not null default false;

comment on column public.documents.suspicious_flags is
  'Flags from prompt-injection / malware heuristics; never grants permissions.';
