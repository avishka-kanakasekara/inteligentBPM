"""Text extractors for supported document types."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from app.security.errors import ValidationAppError


@dataclass
class ExtractedSection:
    heading: str | None
    text: str
    page_number: int | None = None


@dataclass
class ExtractionResult:
    text: str
    sections: list[ExtractedSection] = field(default_factory=list)
    page_count: int = 1
    parser: str = "text"
    metadata: dict[str, str] = field(default_factory=dict)


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValidationAppError("Unable to decode text document")


def extract_text(*, content: bytes, mime_type: str, file_name: str) -> ExtractionResult:
    if mime_type in {"text/plain", "text/markdown"} or file_name.lower().endswith(
        (".txt", ".md", ".markdown")
    ):
        text = _decode_text(content)
        sections = _markdown_sections(text) if file_name.lower().endswith((".md", ".markdown")) else [
            ExtractedSection(heading=None, text=text, page_number=1)
        ]
        return ExtractionResult(
            text=text,
            sections=sections,
            page_count=1,
            parser="text",
        )

    if mime_type == "text/csv" or file_name.lower().endswith(".csv"):
        text = _decode_text(content)
        reader = csv.reader(io.StringIO(text))
        rows = [" | ".join(row) for row in reader]
        joined = "\n".join(rows)
        return ExtractionResult(
            text=joined,
            sections=[ExtractedSection(heading="csv", text=joined, page_number=1)],
            page_count=1,
            parser="csv",
        )

    if mime_type == "message/rfc822" or file_name.lower().endswith(".eml"):
        text = _decode_text(content)
        # Strip headers for body-ish content while keeping subject attribution in metadata
        subject_match = re.search(r"(?im)^Subject:\s*(.+)$", text)
        body = re.split(r"\r?\n\r?\n", text, maxsplit=1)
        body_text = body[1] if len(body) > 1 else text
        return ExtractionResult(
            text=body_text,
            sections=[ExtractedSection(heading="email_body", text=body_text, page_number=1)],
            page_count=1,
            parser="eml",
            metadata={"subject": subject_match.group(1).strip() if subject_match else ""},
        )

    if mime_type == "application/pdf" or file_name.lower().endswith(".pdf"):
        # Foundation extractor: recover readable strings from PDF streams when present.
        # Production would use a dedicated PDF library.
        decoded = content.decode("latin-1", errors="ignore")
        strings = re.findall(r"\((?:\\.|[^\\)]){2,}\)", decoded)
        cleaned = []
        for raw in strings:
            value = raw[1:-1]
            value = value.replace("\\n", "\n").replace("\\r", "").replace("\\(", "(").replace("\\)", ")")
            if value.strip():
                cleaned.append(value)
        text = "\n".join(cleaned).strip()
        if not text:
            # Allow empty for OCR path; pipeline decides failure vs OCR
            return ExtractionResult(text="", sections=[], page_count=1, parser="pdf-stub")
        pages = text.split("\f") if "\f" in text else [text]
        sections = [
            ExtractedSection(heading=f"page_{idx + 1}", text=page, page_number=idx + 1)
            for idx, page in enumerate(pages)
            if page.strip()
        ]
        return ExtractionResult(
            text="\n".join(p.strip() for p in pages if p.strip()),
            sections=sections or [ExtractedSection(heading="page_1", text=text, page_number=1)],
            page_count=max(len(pages), 1),
            parser="pdf-stub",
        )

    if "wordprocessingml" in mime_type or file_name.lower().endswith(".docx"):
        # Minimal DOCX: read UTF-8 strings from zip XML if present
        text = _docx_like_text(content)
        if not text:
            raise ValidationAppError("Failed to parse DOCX content")
        return ExtractionResult(
            text=text,
            sections=[ExtractedSection(heading="body", text=text, page_number=1)],
            page_count=1,
            parser="docx-stub",
        )

    if "spreadsheetml" in mime_type or file_name.lower().endswith(".xlsx"):
        text = _xlsx_like_text(content)
        if not text:
            raise ValidationAppError("Failed to parse XLSX content")
        return ExtractionResult(
            text=text,
            sections=[ExtractedSection(heading="sheet", text=text, page_number=1)],
            page_count=1,
            parser="xlsx-stub",
        )

    if file_name.lower().endswith(".msg"):
        text = _decode_text(content)
        return ExtractionResult(
            text=text,
            sections=[ExtractedSection(heading="msg", text=text, page_number=1)],
            page_count=1,
            parser="msg-stub",
        )

    raise ValidationAppError(
        "No extractor available for file type",
        details={"mime_type": mime_type, "file_name": file_name},
    )


def _markdown_sections(text: str) -> list[ExtractedSection]:
    sections: list[ExtractedSection] = []
    current_heading: str | None = None
    buffer: list[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            if buffer:
                sections.append(
                    ExtractedSection(
                        heading=current_heading,
                        text="\n".join(buffer).strip(),
                        page_number=1,
                    )
                )
                buffer = []
            current_heading = line.lstrip("#").strip()
        else:
            buffer.append(line)
    if buffer:
        sections.append(
            ExtractedSection(heading=current_heading, text="\n".join(buffer).strip(), page_number=1)
        )
    return [s for s in sections if s.text] or [
        ExtractedSection(heading=None, text=text, page_number=1)
    ]


def _docx_like_text(content: bytes) -> str:
    # Pull text nodes from word/document.xml if present in the zip bytes.
    if not content.startswith(b"PK"):
        raise ValidationAppError("DOCX must be an OpenXML package")
    # Naive: extract between <w:t ...> and </w:t>
    xml_chunks = re.findall(rb"<w:t[^>]*>([^<]*)</w:t>", content)
    if not xml_chunks:
        # Fallback: any readable ascii runs
        ascii_runs = re.findall(rb"[A-Za-z0-9 ,.\-]{4,}", content)
        return " ".join(r.decode("ascii", errors="ignore") for r in ascii_runs[:200]).strip()
    return " ".join(c.decode("utf-8", errors="ignore") for c in xml_chunks).strip()


def _xlsx_like_text(content: bytes) -> str:
    if not content.startswith(b"PK"):
        raise ValidationAppError("XLSX must be an OpenXML package")
    shared = re.findall(rb"<t[^>]*>([^<]*)</t>", content)
    if shared:
        return " | ".join(c.decode("utf-8", errors="ignore") for c in shared[:500]).strip()
    ascii_runs = re.findall(rb"[A-Za-z0-9 ,.\-]{3,}", content)
    return " | ".join(r.decode("ascii", errors="ignore") for r in ascii_runs[:200]).strip()
