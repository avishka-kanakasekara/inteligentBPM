"""Document file validation (type, size, checksum)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.security.errors import ValidationAppError

# Max upload size — overridable via Settings.max_upload_bytes
DEFAULT_MAX_BYTES = 25 * 1024 * 1024

ALLOWED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".eml": "message/rfc822",
    ".msg": "application/vnd.ms-outlook",
}

# Simple magic-byte signatures for binary types we accept.
MAGIC_PREFIXES: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF",),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (b"PK\x03\x04",),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (b"PK\x03\x04",),
}


@dataclass(frozen=True)
class ValidatedFile:
    file_name: str
    mime_type: str
    byte_size: int
    content_hash: str
    extension: str


def _extension(file_name: str) -> str:
    match = re.search(r"(\.[A-Za-z0-9]+)$", file_name.strip())
    return (match.group(1).lower() if match else "")


def checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def validate_upload(
    *,
    file_name: str,
    content: bytes,
    declared_mime: str | None = None,
    max_bytes: int | None = None,
) -> ValidatedFile:
    if max_bytes is None:
        try:
            from app.config import get_settings

            max_bytes = int(get_settings().max_upload_bytes)
        except Exception:  # noqa: BLE001
            max_bytes = DEFAULT_MAX_BYTES
    if not file_name or file_name.strip() in {".", ".."}:
        raise ValidationAppError("file_name is required", details={"field": "file_name"})
    if "/" in file_name or "\\" in file_name:
        raise ValidationAppError(
            "file_name must not contain path separators",
            details={"field": "file_name"},
        )
    if not content:
        raise ValidationAppError("File content is empty", details={"field": "content"})
    if len(content) > max_bytes:
        raise ValidationAppError(
            f"File exceeds maximum size of {max_bytes} bytes",
            details={"byte_size": len(content), "max_bytes": max_bytes},
        )

    ext = _extension(file_name)
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationAppError(
            "Unsupported file type",
            details={"extension": ext, "allowed": sorted(ALLOWED_EXTENSIONS)},
        )

    expected_mime = ALLOWED_EXTENSIONS[ext]
    mime = (declared_mime or expected_mime).split(";")[0].strip().lower()
    # Allow text subtypes to be flexible
    if ext in {".txt", ".md", ".markdown", ".csv"}:
        if not mime.startswith("text/") and mime not in {
            "application/csv",
            "text/csv",
            "text/markdown",
            "text/plain",
            "application/octet-stream",
        }:
            raise ValidationAppError(
                "MIME type does not match text document extension",
                details={"mime_type": mime, "extension": ext},
            )
        mime = expected_mime
    elif mime != expected_mime and mime != "application/octet-stream":
        raise ValidationAppError(
            "MIME type does not match file extension",
            details={"mime_type": mime, "expected": expected_mime},
        )
    else:
        mime = expected_mime

    for prefix in MAGIC_PREFIXES.get(mime, ()):
        if not content.startswith(prefix):
            raise ValidationAppError(
                "File content does not match declared type (magic bytes)",
                details={"mime_type": mime},
            )

    # Reject executable-looking payloads disguised as text
    if content[:2] in {b"MZ", b"\x7fE"} or content.startswith(b"#!/"):
        if ext not in {".txt", ".md", ".markdown", ".csv", ".eml"}:
            raise ValidationAppError("Suspicious executable content detected")

    return ValidatedFile(
        file_name=file_name.strip(),
        mime_type=mime,
        byte_size=len(content),
        content_hash=checksum(content),
        extension=ext,
    )
