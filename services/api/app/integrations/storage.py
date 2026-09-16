"""Supabase Storage signed upload URL integration (mockable)."""

from __future__ import annotations

from uuid import UUID

from app.config import Settings, get_settings


class StorageIntegration:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def create_upload_url(
        self,
        *,
        organization_id: UUID,
        filename: str,
        content_type: str,
    ) -> dict[str, str]:
        safe_name = filename.replace("/", "_")
        path = f"{organization_id}/{safe_name}"
        base = (self.settings.supabase_url or "https://example.supabase.co").rstrip("/")
        # Mock signed URL until service credentials are configured.
        return {
            "bucket": "documents",
            "path": path,
            "upload_url": f"{base}/storage/v1/object/upload/sign/documents/{path}",
            "content_type": content_type,
        }
