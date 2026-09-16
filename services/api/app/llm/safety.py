"""Safety configuration for Gemini generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SafetyThreshold:
    category: str
    threshold: str


DEFAULT_THRESHOLDS: tuple[SafetyThreshold, ...] = (
    SafetyThreshold("HARM_CATEGORY_HATE_SPEECH", "BLOCK_MEDIUM_AND_ABOVE"),
    SafetyThreshold("HARM_CATEGORY_DANGEROUS_CONTENT", "BLOCK_MEDIUM_AND_ABOVE"),
    SafetyThreshold("HARM_CATEGORY_SEXUALLY_EXPLICIT", "BLOCK_MEDIUM_AND_ABOVE"),
    SafetyThreshold("HARM_CATEGORY_HARASSMENT", "BLOCK_MEDIUM_AND_ABOVE"),
)


@dataclass
class SafetyConfiguration:
    """Vertex safety settings — never weakened by document content."""

    thresholds: tuple[SafetyThreshold, ...] = DEFAULT_THRESHOLDS
    block_on_safety: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def to_sdk_dicts(self) -> list[dict[str, str]]:
        return [
            {"category": item.category, "threshold": item.threshold}
            for item in self.thresholds
        ]
