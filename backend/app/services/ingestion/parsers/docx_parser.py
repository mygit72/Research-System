"""DOCX parsing via python-docx: heading levels come from paragraph styles."""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document as load_docx
from docx.document import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph as DocxParagraph

from app.services.ingestion.cleaning import clean_text
from app.services.ingestion.parsers.base import ParseError, ProgressCallback, noop_progress
from app.services.ingestion.parsers.common import CAPTION_RE, table_to_markdown
from app.services.ingestion.types import (
    BlockKind,
    DocumentFormat,
    PageInfo,
    RawDocument,
    RawTable,
    TextBlock,
)

_HEADING_STYLE = re.compile(r"^heading\s*(\d)", re.I)


def _iter_body(document: DocxDocument) -> list[DocxParagraph | Table]:
    """Paragraphs and tables in document order."""
    items: list[DocxParagraph | Table] = []
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            items.append(DocxParagraph(child, document))
        elif tag == "tbl":
            items.append(Table(child, document))
    return items


class DocxParser:
    name = "python-docx"
    formats = frozenset({DocumentFormat.DOCX})

    def parse(self, path: Path, progress: ProgressCallback | None = None) -> RawDocument:
        progress = progress or noop_progress
        try:
            document = load_docx(str(path))
        except Exception as exc:
            raise ParseError(
                "We couldn't open this Word document. It may be corrupted.", detail=repr(exc)
            ) from exc

        blocks: list[TextBlock] = []
        tables: list[RawTable] = []
        items = _iter_body(document)
        for index, item in enumerate(items):
            if index % 50 == 0:
                progress("parsing", index / max(len(items), 1), "Reading document")
            if isinstance(item, Table):
                rows = [[clean_text(cell.text) for cell in row.cells] for row in item.rows]
                rows = [row for row in rows if any(row)]
                if len(rows) >= 2:
                    tables.append(RawTable(page=1, rows=rows))
                    blocks.append(
                        TextBlock(text=table_to_markdown(rows), page=1, kind=BlockKind.TABLE)
                    )
                continue
            text = clean_text(item.text)
            if not text:
                continue
            style = (item.style.name if item.style is not None else "") or ""
            match = _HEADING_STYLE.match(style)
            if style.lower() == "title":
                blocks.append(TextBlock(text=text, page=1, kind=BlockKind.HEADING, heading_level=0))
            elif match:
                level = max(1, int(match.group(1)))
                blocks.append(
                    TextBlock(text=text, page=1, kind=BlockKind.HEADING, heading_level=level)
                )
            elif "list" in style.lower():
                blocks.append(TextBlock(text=text, page=1, kind=BlockKind.LIST_ITEM))
            elif CAPTION_RE.match(text) or style.lower() == "caption":
                blocks.append(TextBlock(text=text, page=1, kind=BlockKind.CAPTION))
            else:
                bold = bool(item.runs) and all(run.bold for run in item.runs if run.text.strip())
                blocks.append(TextBlock(text=text, page=1, bold=bold))

        if not blocks:
            raise ParseError("This Word document doesn't contain any text.")
        props = document.core_properties
        metadata = {
            key: value
            for key, value in {
                "title": props.title,
                "author": props.author,
                "keywords": props.keywords,
                "creationDate": props.created.isoformat() if props.created else None,
            }.items()
            if value
        }
        return RawDocument(
            format=DocumentFormat.DOCX,
            pages=[PageInfo(number=1)],
            blocks=blocks,
            tables=tables,
            embedded_metadata=metadata,
            paginated=False,
            parser=self.name,
        )
