"""Sensitive-field filtering for structured logs — never emit secrets or bulk PII."""

from __future__ import annotations

import re
from typing import Any

# Keys / substrings that must never appear in logs as plaintext values.
SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "access_token",
    "refresh_token",
    "id_token",
    "private_key",
    "client_secret",
    "email_password",
    "smtp_password",
    "credential",
    "cookie",
    "set-cookie",
    "session",
    "reasoning",
    "chain_of_thought",
    "hidden_prompt",
    "system_prompt",
    "raw_document",
    "document_content",
    "email_body",
    "email_content",
    "contract_text",
    "full_text",
    "file_bytes",
    "content_base64",
    "content_b64",
)

# Bulk content keys — truncate aggressively even if not secret-named.
BULK_CONTENT_KEYS = (
    "body",
    "content",
    "raw_text",
    "document",
    "contract",
    "message",
    "prompt",
    "completion",
    "response_text",
)

_SECRET_INLINE = re.compile(
    r"(?i)\b(api[_-]?key|password|secret|token|authorization|bearer|access[_-]?token)\b\s*[:=]\s*\S+"
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_PHONE = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _is_bulk_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(part == lowered or lowered.endswith(f"_{part}") for part in BULK_CONTENT_KEYS)


def redact_string(value: str, *, max_len: int = 200) -> str:
    text = _SECRET_INLINE.sub(r"\1=[REDACTED]", value)
    text = _JWT.sub("[REDACTED_TOKEN]", text)
    text = _EMAIL.sub("[REDACTED_EMAIL]", text)
    text = _PHONE.sub("[REDACTED_PHONE]", text)
    if len(text) > max_len:
        return text[:max_len] + "…"
    return text


def sanitize_for_log(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if depth > 6:
        return "[TRUNCATED_DEPTH]"
    if _is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, str):
        if _is_bulk_key(key):
            return redact_string(value, max_len=80)
        return redact_string(value)
    if isinstance(value, dict):
        return {k: sanitize_for_log(v, key=str(k), depth=depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) > 20:
            return [sanitize_for_log(v, key=key, depth=depth + 1) for v in value[:20]] + [
                f"…(+{len(value) - 20} more)"
            ]
        return [sanitize_for_log(v, key=key, depth=depth + 1) for v in value]
    if isinstance(value, (bytes, bytearray)):
        return f"[BYTES:{len(value)}]"
    return value


def sensitive_log_filter_processor(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor that redacts sensitive fields before JSON render."""
    return sanitize_for_log(event_dict)  # type: ignore[return-value]
