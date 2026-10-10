"""Parser registry: one ParserProvider per document format.

Adding a format = implement `ParserProvider` and register it here.
"""

from __future__ import annotations

from app.services.ingestion.ocr import OCRProvider
from app.services.ingestion.parsers.base import ParseError, ParserProvider, ProgressCallback
from app.services.ingestion.parsers.docx_parser import DocxParser
from app.services.ingestion.parsers.html import HTMLParser
from app.services.ingestion.parsers.pdf import PDFParser
from app.services.ingestion.parsers.text import MarkdownParser, TextParser
from app.services.ingestion.types import DocumentFormat


class ParserRegistry:
    def __init__(self, parsers: list[ParserProvider]) -> None:
        self._by_format: dict[DocumentFormat, ParserProvider] = {}
        for parser in parsers:
            for fmt in parser.formats:
                self._by_format[fmt] = parser

    def for_format(self, fmt: DocumentFormat) -> ParserProvider:
        try:
            return self._by_format[fmt]
        except KeyError as exc:
            raise ParseError(f"Files of type {fmt.value} aren't supported yet.") from exc


def default_registry(ocr: OCRProvider) -> ParserRegistry:
    return ParserRegistry(
        [PDFParser(ocr), DocxParser(), HTMLParser(), MarkdownParser(), TextParser()]
    )


__all__ = ["ParseError", "ParserProvider", "ParserRegistry", "ProgressCallback", "default_registry"]
