-- Document similarity and hybrid search functions (organization-scoped).

create or replace function public.match_document_chunks(
  p_organization_id uuid,
  p_query_embedding vector(1536),
  p_match_count integer default 8,
  p_document_id uuid default null
)
returns table (
  chunk_id uuid,
  document_id uuid,
  organization_id uuid,
  chunk_index integer,
  content text,
  similarity double precision,
  metadata jsonb
)
language sql
stable
security invoker
set search_path = public
as $$
  select
    c.id as chunk_id,
    c.document_id,
    c.organization_id,
    c.chunk_index,
    c.content,
    (1 - (c.embedding <=> p_query_embedding))::double precision as similarity,
    c.metadata
  from public.document_chunks c
  where c.organization_id = p_organization_id
    and public.is_org_member(p_organization_id)
    and c.embedding is not null
    and (p_document_id is null or c.document_id = p_document_id)
  order by c.embedding <=> p_query_embedding
  limit greatest(p_match_count, 1);
$$;

create or replace function public.keyword_search_document_chunks(
  p_organization_id uuid,
  p_query text,
  p_match_count integer default 8,
  p_document_id uuid default null
)
returns table (
  chunk_id uuid,
  document_id uuid,
  organization_id uuid,
  chunk_index integer,
  content text,
  rank double precision,
  metadata jsonb
)
language sql
stable
security invoker
set search_path = public
as $$
  select
    c.id as chunk_id,
    c.document_id,
    c.organization_id,
    c.chunk_index,
    c.content,
    ts_rank_cd(c.content_tsv, websearch_to_tsquery('english', p_query))::double precision as rank,
    c.metadata
  from public.document_chunks c
  where c.organization_id = p_organization_id
    and public.is_org_member(p_organization_id)
    and c.content_tsv @@ websearch_to_tsquery('english', p_query)
    and (p_document_id is null or c.document_id = p_document_id)
  order by rank desc
  limit greatest(p_match_count, 1);
$$;

create or replace function public.hybrid_search_document_chunks(
  p_organization_id uuid,
  p_query text,
  p_query_embedding vector(1536),
  p_match_count integer default 8,
  p_keyword_weight double precision default 0.4,
  p_vector_weight double precision default 0.6,
  p_document_id uuid default null
)
returns table (
  chunk_id uuid,
  document_id uuid,
  organization_id uuid,
  chunk_index integer,
  content text,
  keyword_rank double precision,
  vector_similarity double precision,
  hybrid_score double precision,
  metadata jsonb
)
language sql
stable
security invoker
set search_path = public
as $$
  with keyword as (
    select
      c.id as chunk_id,
      ts_rank_cd(c.content_tsv, websearch_to_tsquery('english', p_query))::double precision as keyword_rank
    from public.document_chunks c
    where c.organization_id = p_organization_id
      and public.is_org_member(p_organization_id)
      and length(trim(p_query)) > 0
      and c.content_tsv @@ websearch_to_tsquery('english', p_query)
      and (p_document_id is null or c.document_id = p_document_id)
  ),
  semantic as (
    select
      c.id as chunk_id,
      (1 - (c.embedding <=> p_query_embedding))::double precision as vector_similarity
    from public.document_chunks c
    where c.organization_id = p_organization_id
      and public.is_org_member(p_organization_id)
      and c.embedding is not null
      and (p_document_id is null or c.document_id = p_document_id)
  ),
  combined as (
    select
      coalesce(k.chunk_id, s.chunk_id) as chunk_id,
      coalesce(k.keyword_rank, 0)::double precision as keyword_rank,
      coalesce(s.vector_similarity, 0)::double precision as vector_similarity,
      (
        coalesce(k.keyword_rank, 0) * p_keyword_weight
        + coalesce(s.vector_similarity, 0) * p_vector_weight
      )::double precision as hybrid_score
    from keyword k
    full outer join semantic s on s.chunk_id = k.chunk_id
  )
  select
    c.id as chunk_id,
    c.document_id,
    c.organization_id,
    c.chunk_index,
    c.content,
    x.keyword_rank,
    x.vector_similarity,
    x.hybrid_score,
    c.metadata
  from combined x
  join public.document_chunks c on c.id = x.chunk_id
  where c.organization_id = p_organization_id
  order by x.hybrid_score desc
  limit greatest(p_match_count, 1);
$$;

revoke all on function public.match_document_chunks(uuid, vector, integer, uuid) from public;
revoke all on function public.keyword_search_document_chunks(uuid, text, integer, uuid) from public;
revoke all on function public.hybrid_search_document_chunks(uuid, text, vector, integer, double precision, double precision, uuid) from public;

grant execute on function public.match_document_chunks(uuid, vector, integer, uuid)
  to authenticated;
grant execute on function public.keyword_search_document_chunks(uuid, text, integer, uuid)
  to authenticated;
grant execute on function public.hybrid_search_document_chunks(uuid, text, vector, integer, double precision, double precision, uuid)
  to authenticated;
