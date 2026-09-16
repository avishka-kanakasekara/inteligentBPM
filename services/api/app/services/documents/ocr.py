"""OCR adapter — pluggable; foundation marks image-only PDFs as needing OCR."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OcrResult:
    text: str
    used_ocr: bool
    engine: str
    confidence: float | None = None


class OcrAdapter:
    """Adapter interface for OCR providers (Tesseract/cloud)."""

    engine_name = "foundation-ocr-stub"

    def extract_if_needed(self, *, extracted_text: str, mime_type: str, content: bytes) -> OcrResult:
        stripped = extracted_text.strip()
        if stripped:
            return OcrResult(text=extracted_text, used_ocr=False, engine=self.engine_name)
        # Image-only or empty PDF: stub returns empty with flag (production would OCR).
        if mime_type == "application/pdf" and content.startswith(b"%PDF"):
            return OcrResult(
                text="",
                used_ocr=True,
                engine=self.engine_name,
                confidence=0.0,
            )
        return OcrResult(text=extracted_text, used_ocr=False, engine=self.engine_name)
