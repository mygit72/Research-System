"""OCR providers (fallback for scanned PDFs).

`TesseractOCRProvider` uses PyMuPDF's Tesseract integration and needs the
Tesseract binary + language data (included in the Docker image). When it isn't
available, `available()` is False and the pipeline tells the user instead of
silently returning empty text.
"""

from __future__ import annotations

from functools import cached_property
from typing import Protocol

from app.core.logging import get_logger
from app.services.ingestion.native import pymupdf

log = get_logger(__name__)


class OCRProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def page_textpage(self, page: pymupdf.Page) -> pymupdf.TextPage:
        """Return a TextPage with OCR'd text for the page (same API as native text)."""
        ...


class TesseractOCRProvider:
    name = "tesseract"

    def __init__(self, language: str = "eng", dpi: int = 300) -> None:
        self.language = language
        self.dpi = dpi

    @cached_property
    def _tessdata(self) -> str | None:
        try:
            return str(pymupdf.get_tessdata())
        except Exception:  # Tesseract not installed
            return None

    def available(self) -> bool:
        return self._tessdata is not None

    def page_textpage(self, page: pymupdf.Page) -> pymupdf.TextPage:
        return page.get_textpage_ocr(
            language=self.language, dpi=self.dpi, full=True, tessdata=self._tessdata
        )


class DisabledOCRProvider:
    name = "disabled"

    def available(self) -> bool:
        return False

    def page_textpage(self, page: pymupdf.Page) -> pymupdf.TextPage:
        raise RuntimeError("OCR is disabled")


def build_ocr_provider(enabled: bool) -> OCRProvider:
    provider: OCRProvider = TesseractOCRProvider() if enabled else DisabledOCRProvider()
    if enabled and not provider.available():
        log.info("ocr_unavailable", reason="tesseract not installed")
    return provider
