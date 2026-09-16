"""Redaction helpers for sensitive patterns in document text."""

from __future__ import annotations

import re
from dataclasses import dataclass

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|secret|password|token)\b\s*[:=]\s*\S+"
)


@dataclass(frozen=True)
class RedactionResult:
    text: str
    redacted: bool
    patterns: list[str]


def redact_text(text: str, *, enabled: bool = True) -> RedactionResult:
    if not enabled:
        return RedactionResult(text=text, redacted=False, patterns=[])
    patterns: list[str] = []
    out = text
    for name, pattern, replacement in (
        ("email", EMAIL_RE, "[REDACTED_EMAIL]"),
        ("phone", PHONE_RE, "[REDACTED_PHONE]"),
        ("ssn", SSN_RE, "[REDACTED_SSN]"),
        ("secret", SECRET_RE, "[REDACTED_SECRET]"),
    ):
        if pattern.search(out):
            patterns.append(name)
            out = pattern.sub(replacement, out)
    return RedactionResult(text=out, redacted=bool(patterns), patterns=patterns)
