"""Idempotency service for mutating side effects."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from app.repositories.memory_repos import IdempotencyRepository
from app.security.errors import ConflictError


class IdempotencyService:
    def __init__(self, repo: IdempotencyRepository | None = None) -> None:
        self.repo = repo or IdempotencyRepository()

    @staticmethod
    def hash_request(payload: dict[str, Any] | None) -> str:
        encoded = json.dumps(payload or {}, sort_keys=True, default=str)
        return hashlib.sha256(encoded.encode()).hexdigest()

    def begin(
        self,
        *,
        organization_id: UUID,
        scope: str,
        key: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        request_hash = self.hash_request(payload)
        record = self.repo.begin(
            organization_id=organization_id,
            scope=scope,
            key=key,
            request_hash=request_hash,
        )
        if record.status == "completed" and record.response_body is not None:
            return {
                "replay": True,
                "status": record.response_status or 200,
                "body": record.response_body,
            }
        if record.status == "in_progress" and record.request_hash == request_hash:
            # First caller continues; concurrent callers with same key/hash also continue
            # in this foundation (single-process memory store).
            return None
        raise ConflictError("Idempotency key conflict", code="IDEMPOTENCY_CONFLICT")

    def complete(
        self,
        *,
        organization_id: UUID,
        scope: str,
        key: str,
        response_status: int,
        response_body: dict[str, Any],
    ) -> None:
        self.repo.complete(
            organization_id=organization_id,
            scope=scope,
            key=key,
            response_status=response_status,
            response_body=response_body,
        )
