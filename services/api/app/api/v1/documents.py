"""Document upload, ingestion, reprocessing, and search endpoints."""

from __future__ import annotations

import base64
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request

from app.audit import AuditService
from app.auth.deps import (
    OrganizationContext,
    get_current_user,
    ignore_client_organization_id,
    require_permission,
)
from app.contracts.common import Page
from app.contracts.schemas import (
    DocumentChunkResponse,
    DocumentCitationResponse,
    DocumentCreate,
    DocumentIngestRequest,
    DocumentResponse,
    DocumentSearchHitResponse,
    DocumentSearchRequest,
    DocumentSearchResponse,
    DocumentUploadUrlRequest,
    DocumentUploadUrlResponse,
)
from app.integrations.storage import StorageIntegration
from app.middleware.correlation import get_correlation_id
from app.permissions import codes as perm
from app.repositories.memory_repos import DocumentRepository
from app.repositories.query import ListParams, apply_list, list_params
from app.security.jwt import AuthenticatedUser
from app.services.documents import DocumentIngestionService, DocumentSearchService
from app.services.idempotency import IdempotencyService
from app.domain.enums import OrgRole

router = APIRouter(prefix="/documents", tags=["documents"])


def _to_doc(record: object) -> DocumentResponse:
    return DocumentResponse.model_validate(record, from_attributes=True)


@router.post("/upload-url", response_model=DocumentUploadUrlResponse)
async def create_upload_url(
    body: DocumentUploadUrlRequest,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DOCUMENTS_UPLOAD))],
) -> DocumentUploadUrlResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    payload = StorageIntegration().create_upload_url(
        organization_id=org.organization_id,
        filename=body.filename,
        content_type=body.content_type,
    )
    return DocumentUploadUrlResponse(**payload)


@router.post("/ingest", response_model=DocumentResponse, status_code=201)
async def ingest_document(
    body: DocumentIngestRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DOCUMENTS_UPLOAD))],
) -> DocumentResponse:
    """Upload bytes to private org storage and run the ingestion pipeline."""
    ignore_client_organization_id(org.organization_id, body.organization_id)
    try:
        content = base64.b64decode(body.content_base64, validate=True)
    except Exception as exc:  # noqa: BLE001
        from app.security.errors import ValidationAppError

        raise ValidationAppError("content_base64 is not valid base64") from exc

    record = DocumentIngestionService(org.organization_id).ingest(
        title=body.title,
        file_name=body.file_name,
        content=content,
        declared_mime=body.mime_type,
        uploaded_by_user_id=user.id,
        source_type=body.source_type,
        classification=body.classification,
        access_scope=body.access_scope,
        document_type=body.document_type,
        apply_redaction=body.apply_redaction,
        correlation_id=get_correlation_id(request),
        actor_user_id=user.id,
    )
    return _to_doc(record)


@router.post("", response_model=DocumentResponse, status_code=201)
async def create_document(
    body: DocumentCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DOCUMENTS_UPLOAD))],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> DocumentResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    idem = IdempotencyService()
    if idempotency_key:
        replay = idem.begin(
            organization_id=org.organization_id,
            scope="documents.create",
            key=idempotency_key,
            payload=body.model_dump(mode="json"),
        )
        if replay is not None:
            return DocumentResponse.model_validate(replay["body"])

    record = DocumentRepository(org.organization_id).create(
        title=body.title,
        storage_path=body.storage_path,
        uploaded_by_user_id=user.id,
        file_name=body.file_name,
        mime_type=body.mime_type,
        byte_size=body.byte_size,
        content_hash=body.content_hash,
        source_type=body.source_type,
        classification=body.classification,
        access_scope=body.access_scope,
        document_type=body.document_type,
    )
    # If private object already exists for path, run pipeline immediately.
    ingestion = DocumentIngestionService(org.organization_id)
    if body.storage_path in ingestion.store.stored_objects:
        record = ingestion.process(
            record.id,
            correlation_id=get_correlation_id(request),
        )

    AuditService().record(
        organization_id=org.organization_id,
        actor_user_id=user.id,
        action="document.created",
        resource_type="document",
        resource_id=record.id,
        correlation_id=get_correlation_id(request),
    )
    response = _to_doc(record)
    if idempotency_key:
        idem.complete(
            organization_id=org.organization_id,
            scope="documents.create",
            key=idempotency_key,
            response_status=201,
            response_body=response.model_dump(mode="json"),
        )
    return response


@router.get("/search", response_model=DocumentSearchResponse)
async def search_documents_get(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DOCUMENTS_READ))],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    q: str,
    mode: str = "hybrid",
    limit: int = 8,
    similarity_threshold: float = 0.15,
    document_id: UUID | None = None,
    include_agent_context: bool = False,
) -> DocumentSearchResponse:
    return _run_search(
        org=org,
        user=user,
        query=q,
        mode=mode,  # type: ignore[arg-type]
        limit=limit,
        similarity_threshold=similarity_threshold,
        document_id=document_id,
        include_agent_context=include_agent_context,
    )


@router.post("/search", response_model=DocumentSearchResponse)
async def search_documents_post(
    body: DocumentSearchRequest,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DOCUMENTS_READ))],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> DocumentSearchResponse:
    ignore_client_organization_id(org.organization_id, body.organization_id)
    return _run_search(
        org=org,
        user=user,
        query=body.query,
        mode=body.mode,  # type: ignore[arg-type]
        limit=body.limit,
        similarity_threshold=body.similarity_threshold,
        document_id=body.document_id,
        include_agent_context=body.include_agent_context,
    )


def _run_search(
    *,
    org: OrganizationContext,
    user: AuthenticatedUser,
    query: str,
    mode: str,
    limit: int,
    similarity_threshold: float,
    document_id: UUID | None,
    include_agent_context: bool,
) -> DocumentSearchResponse:
    can_read_restricted = org.role in {OrgRole.OWNER, OrgRole.ADMIN, OrgRole.COMPLIANCE, OrgRole.AUDITOR}
    service = DocumentSearchService(org.organization_id)
    hits = service.search(
        query=query,
        mode=mode,  # type: ignore[arg-type]
        limit=limit,
        similarity_threshold=similarity_threshold,
        document_id=document_id,
        user_id=user.id,
        can_read_restricted=can_read_restricted,
    )
    agent_context = service.agent_context_from_hits(hits) if include_agent_context else None
    return DocumentSearchResponse(
        hits=[
            DocumentSearchHitResponse(
                chunk_id=h.chunk_id,
                document_id=h.document_id,
                organization_id=h.organization_id,
                chunk_index=h.chunk_index,
                content=h.content,
                score=h.score,
                page_number=h.page_number,
                section_heading=h.section_heading,
                file_name=h.file_name,
                title=h.title,
                suspicious=h.suspicious,
                citation=DocumentCitationResponse(
                    document_id=h.citation.document_id,
                    chunk_id=h.citation.chunk_id,
                    file_name=h.citation.file_name,
                    page_number=h.citation.page_number,
                    section_heading=h.citation.section_heading,
                    excerpt=h.citation.excerpt,
                ),
            )
            for h in hits
        ],
        agent_context=agent_context,
    )


@router.get("", response_model=Page[DocumentResponse])
async def list_documents(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DOCUMENTS_READ))],
    params: Annotated[ListParams, Depends(list_params)],
) -> Page[DocumentResponse]:
    items = DocumentRepository(org.organization_id).list_all()
    page = apply_list(
        items,
        params,
        search_fields=[
            lambda d: d.title,
            lambda d: d.storage_path,
            lambda d: d.file_name or "",
        ],
        status_getter=lambda d: d.status.value if hasattr(d.status, "value") else str(d.status),
        sort_fields={"title": lambda d: d.title, "created_at": lambda d: d.created_at},
    )
    return Page(
        items=[_to_doc(i) for i in page.items],
        meta=page.meta,
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DOCUMENTS_READ))],
) -> DocumentResponse:
    record = DocumentRepository(org.organization_id).get(document_id)
    return _to_doc(record)


@router.get("/{document_id}/chunks", response_model=list[DocumentChunkResponse])
async def list_document_chunks(
    document_id: UUID,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DOCUMENTS_READ))],
) -> list[DocumentChunkResponse]:
    chunks = DocumentRepository(org.organization_id).list_chunks(document_id)
    return [DocumentChunkResponse.model_validate(c, from_attributes=True) for c in chunks]


@router.post("/{document_id}/reprocess", response_model=DocumentResponse)
async def reprocess_document(
    document_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DOCUMENTS_UPLOAD))],
) -> DocumentResponse:
    record = DocumentIngestionService(org.organization_id).reprocess(
        document_id,
        correlation_id=get_correlation_id(request),
        actor_user_id=user.id,
    )
    return _to_doc(record)


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    org: Annotated[OrganizationContext, Depends(require_permission(perm.DOCUMENTS_DELETE))],
) -> None:
    DocumentRepository(org.organization_id).delete(document_id)
    AuditService().record(
        organization_id=org.organization_id,
        actor_user_id=user.id,
        action="document.deleted",
        resource_type="document",
        resource_id=document_id,
        correlation_id=get_correlation_id(request),
    )
