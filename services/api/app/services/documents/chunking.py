"""Chunking with page and section references."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.documents.extractors import ExtractedSection


@dataclass
class TextChunk:
    chunk_index: int
    content: str
    page_number: int | None
    section_heading: str | None
    start_offset: int
    end_offset: int
    token_count: int


def _approx_tokens(text: str) -> int:
    return max(1, len(text.split()))


def chunk_sections(
    sections: list[ExtractedSection],
    *,
    max_chars: int = 800,
    overlap: int = 80,
) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    index = 0
    global_offset = 0
    for section in sections:
        text = section.text.strip()
        if not text:
            continue
        start = 0
        while start < len(text):
            end = min(len(text), start + max_chars)
            piece = text[start:end].strip()
            if piece:
                chunks.append(
                    TextChunk(
                        chunk_index=index,
                        content=piece,
                        page_number=section.page_number,
                        section_heading=section.heading,
                        start_offset=global_offset + start,
                        end_offset=global_offset + end,
                        token_count=_approx_tokens(piece),
                    )
                )
                index += 1
            if end >= len(text):
                break
            start = max(end - overlap, start + 1)
        global_offset += len(text) + 1
    return chunks
