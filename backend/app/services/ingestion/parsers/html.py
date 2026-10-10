"""HTML parsing with BeautifulSoup: semantic tags drive structure."""

from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup, Tag

from app.services.ingestion.cleaning import clean_text
from app.services.ingestion.parsers.base import ParseError, ProgressCallback, noop_progress
from app.services.ingestion.parsers.common import table_to_markdown
from app.services.ingestion.parsers.text import read_text_file
from app.services.ingestion.types import (
    BlockKind,
    DocumentFormat,
    PageInfo,
    RawDocument,
    RawTable,
    TextBlock,
)

_SKIP = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg"}
_BLOCK_TAGS = {"p", "li", "pre", "blockquote", "figcaption", "caption", "dd", "dt", "td"}


class HTMLParser:
    name = "beautifulsoup"
    formats = frozenset({DocumentFormat.HTML})

    def parse(self, path: Path, progress: ProgressCallback | None = None) -> RawDocument:
        progress = progress or noop_progress
        soup = BeautifulSoup(read_text_file(path), "html.parser")
        for tag in soup.find_all(_SKIP):
            tag.decompose()
        root = soup.find("article") or soup.find("main") or soup.body or soup

        blocks: list[TextBlock] = []
        tables: list[RawTable] = []
        progress("parsing", 0.1, "Reading HTML")
        for element in root.find_all(True):
            if not isinstance(element, Tag) or _inside_handled(element):
                continue
            name = element.name
            if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                text = clean_text(element.get_text(" "))
                if text:
                    blocks.append(
                        TextBlock(
                            text=text, page=1, kind=BlockKind.HEADING, heading_level=int(name[1])
                        )
                    )
            elif name == "table":
                rows = [
                    [clean_text(c.get_text(" ")) for c in tr.find_all(["td", "th"])]
                    for tr in element.find_all("tr")
                ]
                rows = [r for r in rows if any(r)]
                if len(rows) >= 2:
                    caption_tag = element.find("caption")
                    caption = clean_text(caption_tag.get_text(" ")) if caption_tag else None
                    tables.append(RawTable(page=1, rows=rows, caption=caption))
                    if caption:
                        blocks.append(TextBlock(text=caption, page=1, kind=BlockKind.CAPTION))
                    blocks.append(
                        TextBlock(text=table_to_markdown(rows), page=1, kind=BlockKind.TABLE)
                    )
                element.attrs["data-handled"] = "1"
            elif name == "math":
                text = element.get("alttext") or element.get_text(" ")
                if text:
                    blocks.append(
                        TextBlock(text=str(text).strip(), page=1, kind=BlockKind.EQUATION)
                    )
                element.attrs["data-handled"] = "1"
            elif name in _BLOCK_TAGS:
                if name == "td":
                    continue
                if name == "pre":
                    text = element.get_text().strip()
                    kind = BlockKind.CODE
                else:
                    text = clean_text(element.get_text(" "))
                    kind = {
                        "li": BlockKind.LIST_ITEM,
                        "figcaption": BlockKind.CAPTION,
                        "caption": BlockKind.CAPTION,
                    }.get(name, BlockKind.TEXT)
                if text:
                    blocks.append(TextBlock(text=text, page=1, kind=kind))
                element.attrs["data-handled"] = "1"

        if not blocks:  # unstructured HTML: fall back to visible text
            text = clean_text(root.get_text("\n"))
            if text:
                blocks.append(TextBlock(text=text, page=1))
        if not blocks:
            raise ParseError("This HTML file doesn't contain any readable text.")

        metadata: dict[str, str] = {}
        if soup.title and soup.title.string:
            metadata["title"] = clean_text(soup.title.string)
        for meta in soup.find_all("meta"):
            key = str(meta.get("name") or meta.get("property") or "").lower()
            content = meta.get("content")
            if content and key in {
                "citation_title",
                "citation_doi",
                "citation_publication_date",
                "citation_journal_title",
                "citation_conference_title",
                "keywords",
                "description",
                "author",
            }:
                metadata[key] = str(content)
        authors = [
            str(m.get("content")) for m in soup.find_all("meta", attrs={"name": "citation_author"})
        ]
        if authors:
            metadata["citation_authors"] = "; ".join(authors)
        return RawDocument(
            format=DocumentFormat.HTML,
            pages=[PageInfo(number=1)],
            blocks=blocks,
            tables=tables,
            embedded_metadata=metadata,
            paginated=False,
            parser=self.name,
        )


def _inside_handled(element: Tag) -> bool:
    return any(
        parent.attrs.get("data-handled") for parent in element.parents if isinstance(parent, Tag)
    )
