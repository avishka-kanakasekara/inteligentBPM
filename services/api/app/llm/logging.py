"""Redacted logging helpers for LLM traffic."""

from __future__ import annotations

import re
from typing import Any

import structlog

logger = structlog.get_logger("bpm.llm")

_SECRET = re.compile(
    r"(?i)(api[_-]?key|password|secret|token|authorization|bearer)\s*[:=]\s*\S+"
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def redact_text(value: str, *, max_len: int = 500) -> str:
    text = _SECRET.sub(r"\1=[REDACTED]", value)
    text = _EMAIL.sub("[REDACTED_EMAIL]", text)
    if len(text) > max_len:
        return text[:max_len] + "…"
    return text


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in data.items():
        lowered = key.lower()
        if any(s in lowered for s in ("secret", "password", "token", "authorization", "api_key")):
            safe[key] = "[REDACTED]"
        elif isinstance(value, str):
            safe[key] = redact_text(value)
        elif isinstance(value, dict):
            safe[key] = redact_mapping(value)
        else:
            safe[key] = value
    return safe


def log_llm_event(event: str, **fields: Any) -> None:
    from app.security.log_filter import sanitize_for_log

    logger.info(event, **sanitize_for_log(fields))
