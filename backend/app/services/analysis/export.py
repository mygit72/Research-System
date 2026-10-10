"""Exporting a report to Markdown, Word (.docx) or PDF.

The report is first flattened into a list of blocks (heading, paragraph, bullet, table,
small print); each format renders the same blocks, so all three carry the same text,
labels ("Stated by the authors" / "System-generated synthesis"), citations and sources.
Text comes from the sections as the user last edited them.
"""

from __future__ import annotations

import html
import io
import re
from dataclasses import dataclass
from typing import Any

from app.models.report import ResearchReport

KIND_TITLES = {
    "review": "Literature review",
    "gaps": "Research gaps",
    "disagreements": "Potential disagreements",
    "deep_research": "Deep research report",
}


@dataclass
class Block:
    kind: str  # h1 | h2 | h3 | p | li | small | table
    text: str = ""
    rows: list[list[str]] | None = None


def _inline(text: str) -> str:
    """Our Markdown is simple: paragraphs, "- " bullets, **bold**. Strip bold for plain formats."""
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text)


def _text_blocks(text: str) -> list[Block]:
    blocks = []
    for part in re.split(r"\n\s*\n", text.strip()):
        lines = [line for line in part.splitlines() if line.strip()]
        if lines and all(line.lstrip().startswith(("- ", "* ")) for line in lines):
            blocks += [Block("li", line.lstrip()[2:].strip()) for line in lines]
        elif lines:
            blocks.append(Block("p", " ".join(line.strip() for line in lines)))
    return blocks


def _cites(numbers: list[int]) -> str:
    return "".join(f"[{n}]" for n in numbers)


def blocks(report: ResearchReport) -> list[Block]:
    out = [Block("h1", report.title)]
    meta = [KIND_TITLES.get(report.kind, report.kind), report.created_at.strftime("%d %b %Y")]
    if report.document_ids:
        meta.append(f"{len(report.document_ids)} papers")
    if report.generation_config.get("llm_model"):
        meta.append(f"written by {report.generation_config['llm_model']}")
    out.append(Block("small", " · ".join(meta)))
    if report.query:
        out.append(
            Block(
                "p",
                f"**{'Question' if report.kind == 'deep_research' else 'Topic'}:** {report.query}",
            )
        )
    if report.support:
        out.append(Block("small", report.support.get("explanation", "")))

    for section in report.sections:
        out.append(Block("h2", section["title"]))
        kind, data = section.get("kind", "text"), section.get("data") or {}
        if section.get("origin") == "generated" and section.get("label"):
            out.append(Block("small", f"Check: {section['label']}"))
        if kind in ("text", "answer", "chronology", "open"):
            if section.get("text"):
                out += _text_blocks(section["text"])
            elif kind in ("text", "answer"):
                out.append(Block("p", "Not enough evidence in the papers to write this part."))
        elif kind == "table":
            header = ["Paper", "Year", "Approach", "Datasets", "Metrics", "Key result"]
            rows = [
                [
                    r["document"]["title"],
                    str(r["document"].get("year") or ""),
                    r.get("approach", ""),
                    ", ".join(r.get("datasets", [])),
                    ", ".join(r.get("metrics", [])),
                    f"{r.get('result', '')} {_cites(r.get('citations', []))}".strip(),
                ]
                for r in data.get("rows", [])
            ]
            out.append(Block("table", rows=[header, *rows]))
        elif kind == "disagreements":
            for item in data.get("items", []):
                a, b = item["claim_a"], item["claim_b"]
                out.append(Block("h3", f"{item['label']}: {', '.join(item['shared'])}"))
                out.append(
                    Block("li", f"{a['document']['title']}: {a['text']} {_cites(a['citations'])}")
                )
                out.append(
                    Block("li", f"{b['document']['title']}: {b['text']} {_cites(b['citations'])}")
                )
                for entity_kind, diff in (item.get("differences") or {}).items():
                    out.append(
                        Block(
                            "small",
                            f"Different {entity_kind}s — first: {', '.join(diff['a']) or 'none'}; "
                            f"second: {', '.join(diff['b']) or 'none'}",
                        )
                    )
                out.append(Block("small", item.get("note", "")))
        elif kind == "gaps":
            gaps = data.get("gaps", [])
            for origin in ("Stated by the authors", "System-generated synthesis"):
                chosen = [g for g in gaps if g["origin"] == origin]
                if not chosen:
                    continue
                out.append(Block("h3", origin))
                for gap in chosen:
                    papers = "; ".join(p["title"] for p in gap.get("papers", []))
                    cited = _cites(
                        sorted({n for s in gap.get("statements", []) for n in s["citations"]})
                    )
                    out.append(
                        Block(
                            "li", f"**{gap['id']} {gap['title']}.** {gap['text']} {cited}".strip()
                        )
                    )
                    if papers:
                        out.append(Block("small", f"Papers: {papers}"))
            if data.get("directions"):
                out.append(Block("h3", "Suggested directions (system-generated synthesis)"))
                for direction in data["directions"]:
                    out.append(
                        Block(
                            "li", f"{direction['text']} (from {', '.join(direction['based_on'])})"
                        )
                    )

    if report.sources:
        out.append(Block("h2", "Sources"))
        for source in report.sources:
            document = source["document"]
            year = f" ({document['year']})" if document.get("year") else ""
            where = source.get("section_title") or "Front matter"
            quote = " ".join(str(source["quote"]).split())[:240]
            out.append(
                Block(
                    "small",
                    f"[{source['number']}] {document['title']}{year}, {where}, p. "
                    f"{source.get('page_start')}: “{quote}…”",
                )
            )
    return out


# --- renderers -----------------------------------------------------------------------------------


def _md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def to_markdown(report: ResearchReport) -> str:
    lines: list[str] = []
    for block in blocks(report):
        if block.kind == "h1":
            lines += [f"# {block.text}", ""]
        elif block.kind == "h2":
            lines += [f"## {block.text}", ""]
        elif block.kind == "h3":
            lines += [f"### {block.text}", ""]
        elif block.kind == "p":
            lines += [block.text, ""]
        elif block.kind == "li":
            lines.append(f"- {block.text}")
        elif block.kind == "small":
            lines += [f"*{block.text}*", ""]
        elif block.kind == "table" and block.rows:
            lines.append("| " + " | ".join(block.rows[0]) + " |")
            lines.append("|" + "---|" * len(block.rows[0]))
            lines += ["| " + " | ".join(_md_cell(c) for c in row) + " |" for row in block.rows[1:]]
            lines.append("")
    text = "\n".join(lines)
    return re.sub(r"(\n- [^\n]*)\n(?=[^-\n])", r"\1\n\n", text).strip() + "\n"


def to_docx(report: ResearchReport) -> bytes:
    from docx import Document as _docx_document
    from docx.shared import Pt

    new_document: Any = _docx_document  # python-docx is untyped
    doc = new_document()
    for block in blocks(report):
        if block.kind == "h1":
            doc.add_heading(block.text, level=0)
        elif block.kind in ("h2", "h3"):
            doc.add_heading(block.text, level=1 if block.kind == "h2" else 2)
        elif block.kind == "p":
            _docx_runs(doc.add_paragraph(), block.text)
        elif block.kind == "li":
            _docx_runs(doc.add_paragraph(style="List Bullet"), block.text)
        elif block.kind == "small":
            run = doc.add_paragraph().add_run(block.text)
            run.italic = True
            run.font.size = Pt(9)
        elif block.kind == "table" and block.rows:
            table = doc.add_table(rows=len(block.rows), cols=len(block.rows[0]))
            table.style = "Table Grid"
            for r, row in enumerate(block.rows):
                for c, value in enumerate(row):
                    table.cell(r, c).text = value
                    if r == 0:
                        for run in table.cell(r, c).paragraphs[0].runs:
                            run.bold = True
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _docx_runs(paragraph: Any, text: str) -> None:
    for index, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if part:
            paragraph.add_run(part).bold = index % 2 == 1


_CSS = """
body { font-family: sans-serif; font-size: 10.5pt; line-height: 1.4; color: #1b1b19; }
h1 { font-size: 18pt; margin-bottom: 4pt; }
h2 { font-size: 13pt; margin-top: 14pt; }
h3 { font-size: 11pt; margin-top: 8pt; }
p.small { font-size: 8.5pt; color: #62615c; font-style: italic; }
table { border-collapse: collapse; font-size: 8.5pt; }
th, td { border: 1px solid #c9c8c2; padding: 3pt; vertical-align: top; }
"""


def to_html(report: ResearchReport) -> str:
    parts: list[str] = []
    in_list = False
    for block in blocks(report):
        if block.kind != "li" and in_list:
            parts.append("</ul>")
            in_list = False
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(block.text))
        if block.kind in ("h1", "h2", "h3"):
            parts.append(f"<{block.kind}>{text}</{block.kind}>")
        elif block.kind == "p":
            parts.append(f"<p>{text}</p>")
        elif block.kind == "small":
            parts.append(f'<p class="small">{text}</p>')
        elif block.kind == "li":
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{text}</li>")
        elif block.kind == "table" and block.rows:
            head = "".join(f"<th>{html.escape(c)}</th>" for c in block.rows[0])
            body = "".join(
                "<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in row) + "</tr>"
                for row in block.rows[1:]
            )
            parts.append(f"<table><tr>{head}</tr>{body}</table>")
    if in_list:
        parts.append("</ul>")
    return "".join(parts)


def to_pdf(report: ResearchReport) -> bytes:
    from app.services.ingestion.native import pymupdf as _pymupdf

    pymupdf: Any = _pymupdf  # untyped C extension
    story = pymupdf.Story(html=to_html(report), user_css=_CSS)
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    page = pymupdf.paper_rect("a4")
    area = page + (56, 56, -56, -56)  # noqa: RUF005 (pymupdf.Rect arithmetic, not a tuple)
    more = 1
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(area)
        story.draw(device)
        writer.end_page()
    writer.close()
    return buffer.getvalue()


def filename(report: ResearchReport, extension: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", report.title.lower()).strip("-")[:60] or "report"
    return f"{slug}.{extension}"
