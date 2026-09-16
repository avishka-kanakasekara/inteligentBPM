"""Document ingestion pipeline and search services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from app.audit import AuditService
from app.contracts.common import utcnow
from app.database.memory import (
    DocumentChunkRecord,
    DocumentRecord,
    StoredObjectRecord,
    get_memory_store,
    new_id,
)
from app.domain.enums import DocumentStatus
from app.security.errors import ConflictError, NotFoundError, ValidationAppError
from app.services.documents.chunking import chunk_sections
from app.services.documents.embeddings import EmbeddingAdapter
from app.services.documents.extractors import extract_text
from app.services.documents.injection import (
    Citation,
    assemble_agent_context,
    scan_for_injection,
)
from app.services.documents.malware import MalwareScanAdapter
from app.services.documents.ocr import OcrAdapter
from app.services.documents.redaction import redact_text
from app.services.documents.validation import validate_upload

SearchMode = Literal["keyword", "vector", "hybrid"]


@dataclass
class SearchHit:
    chunk_id: UUID
    document_id: UUID
    organization_id: UUID
    chunk_index: int
    content: str
    score: float
    page_number: int | None
    section_heading: str | None
    file_name: str | None
    title: str
    citation: Citation
    suspicious: bool


class ObjectStore:
    def __init__(self) -> None:
        self.store = get_memory_store()

    def put(
        self,
        *,
        organization_id: UUID,
        path: str,
        content: bytes,
        content_type: str,
    ) -> StoredObjectRecord:
        if not path.startswith(f"{organization_id}/"):
            raise ValidationAppError("storage path must be organization-scoped")
        record = StoredObjectRecord(
            organization_id=organization_id,
            path=path,
            content=content,
            content_type=content_type,
            created_at=utcnow(),
        )
        self.store.stored_objects[path] = record
        return record

    def get(self, path: str, *, organization_id: UUID) -> StoredObjectRecord:
        record = self.store.stored_objects.get(path)
        if record is None or record.organization_id != organization_id:
            raise NotFoundError("Stored object not found")
        return record


class DocumentIngestionService:
    def __init__(self, organization_id: UUID) -> None:
        self.organization_id = organization_id
        self.store = get_memory_store()
        self.objects = ObjectStore()
        self.malware = MalwareScanAdapter()
        self.ocr = OcrAdapter()
        self.embeddings = EmbeddingAdapter()
        self.audit = AuditService()

    def _docs(self) -> list[DocumentRecord]:
        return [
            d
            for d in self.store.documents.values()
            if d.organization_id == self.organization_id
        ]

    def get(self, document_id: UUID) -> DocumentRecord:
        record = self.store.documents.get(document_id)
        if record is None or record.organization_id != self.organization_id:
            raise NotFoundError("Document not found")
        return record

    def list_chunks(self, document_id: UUID) -> list[DocumentChunkRecord]:
        self.get(document_id)
        return [
            c
            for c in self.store.document_chunks.values()
            if c.organization_id == self.organization_id and c.document_id == document_id
        ]

    def find_duplicate_hash(self, content_hash: str, *, exclude_id: UUID | None = None) -> DocumentRecord | None:
        for doc in self._docs():
            if doc.content_hash != content_hash:
                continue
            if doc.status in {
                DocumentStatus.FAILED,
                DocumentStatus.QUARANTINED,
                DocumentStatus.ARCHIVED,
            }:
                continue
            if exclude_id is not None and doc.id == exclude_id:
                continue
            return doc
        return None

    def ingest(
        self,
        *,
        title: str,
        file_name: str,
        content: bytes,
        declared_mime: str | None,
        uploaded_by_user_id: UUID | None,
        source_type: str = "upload",
        classification: str = "internal",
        access_scope: str = "organization",
        document_type: str = "general",
        apply_redaction: bool = True,
        correlation_id: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> DocumentRecord:
        validated = validate_upload(
            file_name=file_name,
            content=content,
            declared_mime=declared_mime,
        )
        duplicate = self.find_duplicate_hash(validated.content_hash)
        if duplicate is not None:
            raise ConflictError(
                "Duplicate file content already exists in this organization",
                code="DUPLICATE_DOCUMENT",
                details={"existing_document_id": str(duplicate.id)},
            )

        path = f"{self.organization_id}/{validated.content_hash[:16]}_{validated.file_name}"
        self.objects.put(
            organization_id=self.organization_id,
            path=path,
            content=content,
            content_type=validated.mime_type,
        )

        now = utcnow()
        record = DocumentRecord(
            id=new_id(),
            organization_id=self.organization_id,
            title=title,
            storage_path=path,
            status=DocumentStatus.UPLOADED,
            uploaded_by_user_id=uploaded_by_user_id,
            created_at=now,
            updated_at=now,
            file_name=validated.file_name,
            mime_type=validated.mime_type,
            byte_size=validated.byte_size,
            content_hash=validated.content_hash,
            source_type=source_type,
            classification=classification,
            access_scope=access_scope,
            document_type=document_type,
            owner_user_id=uploaded_by_user_id,
            created_by_user_id=uploaded_by_user_id,
        )
        self.store.documents[record.id] = record
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id or uploaded_by_user_id,
            action="document.uploaded",
            resource_type="document",
            resource_id=record.id,
            correlation_id=correlation_id,
            payload={"file_name": validated.file_name, "mime_type": validated.mime_type},
        )
        return self.process(record.id, apply_redaction=apply_redaction, correlation_id=correlation_id)

    def process(
        self,
        document_id: UUID,
        *,
        apply_redaction: bool = True,
        correlation_id: str | None = None,
    ) -> DocumentRecord:
        record = self.get(document_id)
        try:
            record.status = DocumentStatus.QUEUED
            record.updated_at = utcnow()

            record.status = DocumentStatus.SCANNING
            obj = self.objects.get(record.storage_path, organization_id=self.organization_id)
            scan = self.malware.scan(obj.content, mime_type=record.mime_type or "application/octet-stream")
            if not scan.clean:
                record.status = DocumentStatus.QUARANTINED
                record.failure_reason = f"Malware scan findings: {', '.join(scan.findings)}"
                record.suspicious_flags = list(scan.findings)
                record.updated_at = utcnow()
                self.audit.record(
                    organization_id=self.organization_id,
                    actor_user_id=None,
                    action="document.quarantined",
                    resource_type="document",
                    resource_id=record.id,
                    correlation_id=correlation_id,
                    payload={"findings": scan.findings},
                )
                return record

            record.status = DocumentStatus.EXTRACTING
            extraction = extract_text(
                content=obj.content,
                mime_type=record.mime_type or "application/octet-stream",
                file_name=record.file_name or record.title,
            )
            ocr = self.ocr.extract_if_needed(
                extracted_text=extraction.text,
                mime_type=record.mime_type or "application/octet-stream",
                content=obj.content,
            )
            text = ocr.text if ocr.used_ocr else extraction.text
            sections = extraction.sections
            if ocr.used_ocr and not text.strip():
                # OCR stub with no text → failed processing (retryable via reprocess after OCR configured)
                raise ValidationAppError(
                    "OCR required but no text could be extracted",
                    details={"ocr_engine": ocr.engine},
                )
            if not text.strip() and not sections:
                raise ValidationAppError("Failed to extract text from document")

            if not sections and text.strip():
                from app.services.documents.extractors import ExtractedSection

                sections = [ExtractedSection(heading=None, text=text, page_number=1)]

            injection = scan_for_injection(text)
            record.suspicious_flags = list(injection.flags)
            # Never allow document to modify permissions — we only flag, never elevate.

            record.status = DocumentStatus.CHUNKING
            # Clear previous chunks on reprocess
            for chunk_id, chunk in list(self.store.document_chunks.items()):
                if chunk.document_id == record.id:
                    del self.store.document_chunks[chunk_id]

            raw_chunks = chunk_sections(sections)
            if not raw_chunks:
                raise ValidationAppError("Chunking produced no content")

            record.status = DocumentStatus.EMBEDDING
            embed_model = self.embeddings.model
            embed_dim = self.embeddings.dimension
            now = utcnow()
            for raw in raw_chunks:
                redacted = redact_text(raw.content, enabled=apply_redaction)
                chunk_injection = scan_for_injection(raw.content)
                emb = self.embeddings.embed(redacted.text)
                chunk = DocumentChunkRecord(
                    id=new_id(),
                    organization_id=self.organization_id,
                    document_id=record.id,
                    chunk_index=raw.chunk_index,
                    content=redacted.text,
                    created_at=now,
                    updated_at=now,
                    embedding=emb.vector,
                    token_count=raw.token_count,
                    page_number=raw.page_number,
                    section_heading=raw.section_heading,
                    start_offset=raw.start_offset,
                    end_offset=raw.end_offset,
                    embedding_model=emb.model,
                    is_redacted=redacted.redacted,
                    suspicious=chunk_injection.suspicious,
                    metadata={
                        "redaction_patterns": redacted.patterns,
                        "injection_flags": chunk_injection.flags,
                        "source_offsets": {
                            "start": raw.start_offset,
                            "end": raw.end_offset,
                        },
                    },
                )
                self.store.document_chunks[chunk.id] = chunk

            record.status = DocumentStatus.INDEXED
            record.embedding_model = embed_model
            record.embedding_dimension = embed_dim
            record.page_count = extraction.page_count
            record.section_count = len(sections)
            record.chunk_count = len(raw_chunks)
            record.redacted = apply_redaction
            record.failure_reason = None
            record.version_number += 0 if record.version_number else 1
            record.metadata = {
                **record.metadata,
                "parser": extraction.parser,
                "ocr_used": ocr.used_ocr,
                "malware_engine": scan.engine,
            }
            record.updated_at = utcnow()
            self.audit.record(
                organization_id=self.organization_id,
                actor_user_id=None,
                action="document.indexed",
                resource_type="document",
                resource_id=record.id,
                correlation_id=correlation_id,
                payload={"chunk_count": record.chunk_count, "suspicious_flags": record.suspicious_flags},
            )
            return record
        except Exception as exc:  # noqa: BLE001 — convert to failed processing state
            record.status = DocumentStatus.FAILED
            record.failure_reason = str(exc)
            record.updated_at = utcnow()
            self.audit.record(
                organization_id=self.organization_id,
                actor_user_id=None,
                action="document.failed",
                resource_type="document",
                resource_id=record.id,
                correlation_id=correlation_id,
                payload={"failure_reason": record.failure_reason},
            )
            return record

    def reprocess(
        self,
        document_id: UUID,
        *,
        apply_redaction: bool = True,
        correlation_id: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> DocumentRecord:
        record = self.get(document_id)
        record.version_number += 1
        self.audit.record(
            organization_id=self.organization_id,
            actor_user_id=actor_user_id,
            action="document.reprocess_requested",
            resource_type="document",
            resource_id=record.id,
            correlation_id=correlation_id,
            payload={"version_number": record.version_number},
        )
        return self.process(
            document_id,
            apply_redaction=apply_redaction,
            correlation_id=correlation_id,
        )


class DocumentSearchService:
    def __init__(self, organization_id: UUID) -> None:
        self.organization_id = organization_id
        self.store = get_memory_store()
        self.embeddings = EmbeddingAdapter()

    def _visible_documents(
        self,
        *,
        user_id: UUID | None,
        can_read_restricted: bool,
    ) -> dict[UUID, DocumentRecord]:
        visible: dict[UUID, DocumentRecord] = {}
        for doc in self.store.documents.values():
            if doc.organization_id != self.organization_id:
                continue
            if doc.status != DocumentStatus.INDEXED:
                continue
            if doc.access_scope == "owner" and user_id and doc.owner_user_id != user_id:
                if not can_read_restricted:
                    continue
            if doc.access_scope == "restricted" and not can_read_restricted:
                continue
            visible[doc.id] = doc
        return visible

    def search(
        self,
        *,
        query: str,
        mode: SearchMode = "hybrid",
        limit: int = 8,
        similarity_threshold: float = 0.15,
        document_id: UUID | None = None,
        user_id: UUID | None = None,
        can_read_restricted: bool = False,
    ) -> list[SearchHit]:
        if not query.strip():
            raise ValidationAppError("query is required")
        visible = self._visible_documents(
            user_id=user_id,
            can_read_restricted=can_read_restricted,
        )
        if document_id is not None and document_id not in visible:
            return []

        chunks = [
            c
            for c in self.store.document_chunks.values()
            if c.organization_id == self.organization_id
            and c.document_id in visible
            and (document_id is None or c.document_id == document_id)
        ]

        query_emb = self.embeddings.embed(query).vector
        keywords = [t for t in re_tokens(query)]

        scored: list[tuple[float, DocumentChunkRecord, DocumentRecord]] = []
        for chunk in chunks:
            doc = visible[chunk.document_id]
            keyword_score = keyword_rank(chunk.content, keywords)
            vector_score = (
                self.embeddings.cosine(query_emb, chunk.embedding or [])
                if chunk.embedding
                else 0.0
            )
            if mode == "keyword":
                score = keyword_score
                if score <= 0:
                    continue
            elif mode == "vector":
                score = vector_score
                if score < similarity_threshold:
                    continue
            else:
                score = 0.4 * keyword_score + 0.6 * vector_score
                if score < similarity_threshold and keyword_score <= 0:
                    continue
            scored.append((score, chunk, doc))

        scored.sort(key=lambda item: item[0], reverse=True)
        hits: list[SearchHit] = []
        for score, chunk, doc in scored[: max(limit, 1)]:
            citation = Citation(
                document_id=str(doc.id),
                chunk_id=str(chunk.id),
                file_name=doc.file_name,
                page_number=chunk.page_number,
                section_heading=chunk.section_heading,
                excerpt=chunk.content[:500],
            )
            hits.append(
                SearchHit(
                    chunk_id=chunk.id,
                    document_id=doc.id,
                    organization_id=doc.organization_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    score=score,
                    page_number=chunk.page_number,
                    section_heading=chunk.section_heading,
                    file_name=doc.file_name,
                    title=doc.title,
                    citation=citation,
                    suspicious=chunk.suspicious or bool(doc.suspicious_flags),
                )
            )
        return hits

    def agent_context_from_hits(self, hits: list[SearchHit]) -> str:
        return assemble_agent_context(citations=[h.citation for h in hits])


def re_tokens(text: str) -> list[str]:
    import re

    return re.findall(r"[a-z0-9]+", text.lower())


def keyword_rank(content: str, keywords: list[str]) -> float:
    if not keywords:
        return 0.0
    hay = content.lower()
    hits = sum(1 for kw in keywords if kw in hay)
    return hits / len(keywords)
