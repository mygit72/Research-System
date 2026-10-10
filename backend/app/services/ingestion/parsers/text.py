"""Plain-text and Markdown parsing."""

from __future__ import annotations

import re
from pathlib import Path

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

# "1 Introduction", "2.3 Training details", "III. METHODS"
NUMBERED_HEADING = re.compile(r"^(?:(\d+(?:\.\d+)*)\.?|([IVX]+)\.)\s+([A-Z][^.!?]{1,90})$")
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_MD_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _paragraphs(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


class TextParser:
    name = "plaintext"
    formats = frozenset({DocumentFormat.TEXT})

    def parse(self, path: Path, progress: ProgressCallback | None = None) -> RawDocument:
        (progress or noop_progress)("parsing", 0.1, "Reading text")
        blocks: list[TextBlock] = []
        for chunk in _paragraphs(read_text_file(path)):
            stripped = chunk.strip()
            single_line = "\n" not in stripped
            match = NUMBERED_HEADING.match(stripped) if single_line else None
            if match:
                number = match.group(1) or match.group(2)
                level = number.count(".") + 1 if match.group(1) else 1
                blocks.append(
                    TextBlock(text=stripped, page=1, kind=BlockKind.HEADING, heading_level=level)
                )
            elif single_line and len(stripped) < 60 and stripped.isupper():
                blocks.append(
                    TextBlock(
                        text=stripped.title(), page=1, kind=BlockKind.HEADING, heading_level=1
                    )
                )
            else:
                text = clean_text(stripped)
                kind = BlockKind.CAPTION if CAPTION_RE.match(text) else BlockKind.TEXT
                blocks.append(TextBlock(text=text, page=1, kind=kind))
        if not blocks:
            raise ParseError("This text file is empty.")
        return RawDocument(
            format=DocumentFormat.TEXT,
            pages=[PageInfo(number=1)],
            blocks=blocks,
            paginated=False,
            parser=self.name,
        )


class MarkdownParser:
    name = "markdown"
    formats = frozenset({DocumentFormat.MARKDOWN})

    def parse(self, path: Path, progress: ProgressCallback | None = None) -> RawDocument:
        (progress or noop_progress)("parsing", 0.1, "Reading Markdown")
        lines = read_text_file(path).replace("\r\n", "\n").split("\n")
        blocks: list[TextBlock] = []
        tables: list[RawTable] = []
        buffer: list[str] = []

        def flush() -> None:
            if buffer:
                text = clean_text("\n".join(buffer))
                if text:
                    is_list = bool(re.match(r"^([-*+]|\d+\.)\s", buffer[0].strip()))
                    kind = (
                        BlockKind.CAPTION
                        if CAPTION_RE.match(text)
                        else BlockKind.LIST_ITEM
                        if is_list
                        else BlockKind.TEXT
                    )
                    blocks.append(TextBlock(text=text, page=1, kind=kind))
                buffer.clear()

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if stripped.startswith(("```", "~~~")):
                flush()
                fence = stripped[:3]
                code: list[str] = []
                i += 1
                while i < len(lines) and not lines[i].strip().startswith(fence):
                    code.append(lines[i])
                    i += 1
                if code:
                    blocks.append(TextBlock(text="\n".join(code), page=1, kind=BlockKind.CODE))
            elif stripped.startswith("$$"):
                flush()
                math = [stripped[2:]]
                if not (stripped.endswith("$$") and len(stripped) > 2):
                    i += 1
                    while i < len(lines) and "$$" not in lines[i]:
                        math.append(lines[i])
                        i += 1
                    if i < len(lines):
                        math.append(lines[i].replace("$$", ""))
                expr = " ".join(part.strip() for part in math).replace("$$", "").strip()
                if expr:
                    blocks.append(TextBlock(text=expr, page=1, kind=BlockKind.EQUATION))
            elif (match := _MD_HEADING.match(stripped)) is not None:
                flush()
                blocks.append(
                    TextBlock(
                        text=clean_text(match.group(2)),
                        page=1,
                        kind=BlockKind.HEADING,
                        heading_level=len(match.group(1)),
                    )
                )
            elif (
                stripped.startswith("|")
                and i + 1 < len(lines)
                and _MD_TABLE_SEP.match(lines[i + 1])
            ):
                flush()
                rows = [_md_row(stripped)]
                i += 2
                while i < len(lines) and lines[i].strip().startswith("|"):
                    rows.append(_md_row(lines[i].strip()))
                    i += 1
                tables.append(RawTable(page=1, rows=rows))
                blocks.append(TextBlock(text=table_to_markdown(rows), page=1, kind=BlockKind.TABLE))
                continue
            elif not stripped:
                flush()
            elif re.match(r"^([-*+]|\d+\.)\s", stripped):
                flush()
                buffer.append(stripped)
            else:
                buffer.append(line)
            i += 1
        flush()
        if not blocks:
            raise ParseError("This Markdown file is empty.")
        return RawDocument(
            format=DocumentFormat.MARKDOWN,
            pages=[PageInfo(number=1)],
            blocks=blocks,
            tables=tables,
            paginated=False,
            parser=self.name,
        )


def _md_row(line: str) -> list[str]:
    return [clean_text(cell) for cell in line.strip().strip("|").split("|")]
