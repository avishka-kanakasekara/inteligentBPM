"""LLM failure classification and typed errors."""

from __future__ import annotations

import re
from typing import Any

from app.llm.types import LLMFailureKind


class LLMError(Exception):
    def __init__(
        self,
        message: str,
        *,
        kind: LLMFailureKind,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.retryable = retryable
        self.details = details or {}


class LLMFailureClassifier:
    """Maps provider/SDK errors into stable failure kinds."""

    _RATE = re.compile(r"(?i)rate.?limit|429|resource.?exhausted")
    _QUOTA = re.compile(r"(?i)quota|billing|exceeded.*limit")
    _TIMEOUT = re.compile(r"(?i)timeout|timed out|deadline")
    _SAFETY = re.compile(r"(?i)safety|blocked|harm.?category|responsible.?ai")
    _UNAVAIL = re.compile(r"(?i)unavailable|not found|404|model.*does not exist|503")
    _JSON = re.compile(r"(?i)json|parse|schema|mime")

    def classify(self, exc: BaseException) -> LLMError:
        if isinstance(exc, LLMError):
            return exc
        text = f"{type(exc).__name__}: {exc}"
        if self._TIMEOUT.search(text):
            return LLMError(text, kind=LLMFailureKind.TIMEOUT, retryable=True)
        if self._RATE.search(text):
            return LLMError(text, kind=LLMFailureKind.RATE_LIMIT, retryable=True)
        if self._QUOTA.search(text):
            return LLMError(text, kind=LLMFailureKind.QUOTA, retryable=False)
        if self._SAFETY.search(text):
            return LLMError(text, kind=LLMFailureKind.SAFETY_BLOCK, retryable=False)
        if self._UNAVAIL.search(text):
            return LLMError(text, kind=LLMFailureKind.MODEL_UNAVAILABLE, retryable=True)
        if self._JSON.search(text):
            return LLMError(text, kind=LLMFailureKind.INVALID_JSON, retryable=True)
        # Default: treat unknown provider errors as transient once
        return LLMError(text, kind=LLMFailureKind.TRANSIENT, retryable=True)

    def from_blocked(self, reason: str | None) -> LLMError:
        return LLMError(
            f"Model response blocked by safety: {reason or 'unknown'}",
            kind=LLMFailureKind.SAFETY_BLOCK,
            retryable=False,
            details={"block_reason": reason},
        )
