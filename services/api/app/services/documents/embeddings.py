"""Embedding generation adapter — deterministic local vectors for foundation mode."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass

DEFAULT_MODEL = "foundation-hash-embedding-v1"
DEFAULT_DIMENSION = 1536


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    model: str
    dimension: int


class EmbeddingAdapter:
    """Produces stable pseudo-embeddings without calling an external LLM API."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        dimension: int = DEFAULT_DIMENSION,
    ) -> None:
        self.model = model
        self.dimension = dimension

    def embed(self, text: str) -> EmbeddingResult:
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        vector = [0.0] * self.dimension
        if not tokens:
            return EmbeddingResult(vector=vector, model=self.model, dimension=self.dimension)
        for token in tokens:
            digest = hashlib.sha256(token.encode()).digest()
            for i in range(0, 32, 4):
                idx = int.from_bytes(digest[i : i + 4], "big") % self.dimension
                sign = 1.0 if digest[i] % 2 == 0 else -1.0
                vector[idx] += sign
        # L2 normalize
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        vector = [v / norm for v in vector]
        return EmbeddingResult(vector=vector, model=self.model, dimension=self.dimension)

    def cosine(self, a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        return sum(x * y for x, y in zip(a, b, strict=True))
