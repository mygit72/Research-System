"""Exporting a project: the plan (Markdown / Word) and the outline as LaTeX (+ BibTeX).

The LaTeX bundle is a .zip with `main.tex` and `references.bib`, ready for Overleaf:
passage citations `[n]` become `\\cite{key}` of the paper the passage is from, with keys
from the same BibTeX export the collections use.
"""

from __future__ import annotations

import io
import re
import uuid
import zipfile
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import ResearchProject
from app.services import organization as org
from app.services.citation_export import bibtex, citation_keys
from app.services.projects.service import _steps

_CITE_RUN = re.compile(r"(?:\[\d+\])+")
_LATEX_SPECIAL = str.maketrans(
    {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
     "~": r"\textasciitilde{}", "^": r"\textasciicircum{}", "\\": r"\textbackslash{}"}
)  # fmt: skip


def plan_markdown(project: ResearchProject, reports: dict[str, Any]) -> str:
    steps = _steps(project)
    lines = [f"# {project.title}", "", f"**Idea:** {project.idea}", ""]
    lines += ["## Research question", "", project.question or "_Not chosen yet._", ""]
    gap = steps["gaps"].get("chosen")
    lines += ["## Gap and hypothesis", ""]
    if gap:
        lines += [
            f"**Gap ({gap.get('origin', '')}):** {gap.get('title', '')} — {gap.get('text', '')}",
            "",
        ]
    lines += [f"**Hypothesis:** {project.hypothesis or '_Not written yet._'}", ""]
    background = reports.get("background")
    if background is not None:
        lines += [
            "## Background",
            "",
            f"Literature review: “{background.title}” ({background.status}).",
            "",
        ]
    chosen = steps["methods"]["chosen"]
    lines += ["## Method plan", ""]
    for label, key in (
        ("Builds on", "methods"),
        ("Baselines", "baselines"),
        ("Datasets", "datasets"),
        ("Metrics", "metrics"),
    ):
        lines.append(f"- **{label}:** {', '.join(chosen.get(key) or []) or '—'}")
    lines += ["", "## Experiments", ""]
    for item in steps["experiments"]["items"]:
        lines.append(
            f"- **{item['title']}** — {item['setup']}. Goal: {item['goal']} "
            f"Metrics: {', '.join(item.get('metrics', []))}."
        )
        if item.get("notes"):
            lines.append(f"  - Notes: {item['notes']}")
    if not steps["experiments"]["items"]:
        lines.append("_Not planned yet._")
    milestones = steps["experiments"]["milestones"]
    if milestones:
        lines += ["", "## Milestones", ""]
        lines += [
            f"- [{'x' if m.get('done') else ' '}] {m['due']} — {m['title']}" for m in milestones
        ]
    outline = steps["outline"]["sections"]
    if outline:
        lines += ["", "## Paper outline", ""]
        for section in outline:
            lines += [f"### {section['title']}", "", section.get("text") or "_Empty._", ""]
        sources = steps["outline"]["sources"]
        if sources:
            lines += ["### Sources", ""]
            lines += [
                f"[{s['number']}] {s['document']['title']}, p. {s.get('page_start')}"
                for s in sources
            ]
    return "\n".join(lines).rstrip() + "\n"


def plan_docx(markdown: str) -> bytes:
    from docx import Document as _docx_document

    new_document: Any = _docx_document  # python-docx is untyped
    doc = new_document()
    for line in markdown.splitlines():
        if line.startswith("# "):
            doc.add_heading(line[2:], level=0)
        elif line.startswith("## "):
            doc.add_heading(line[3:], level=1)
        elif line.startswith("### "):
            doc.add_heading(line[4:], level=2)
        elif line.startswith(("- ", "  - ")):
            _runs(doc.add_paragraph(style="List Bullet"), line.strip()[2:])
        elif line.strip():
            _runs(doc.add_paragraph(), line)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _runs(paragraph: Any, text: str) -> None:
    text = text.replace("_Not chosen yet._", "Not chosen yet.").replace(
        "_Not written yet._", "Not written yet."
    )
    for index, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if part:
            paragraph.add_run(part).bold = index % 2 == 1


def _latex(text: str) -> str:
    return text.translate(_LATEX_SPECIAL)


async def outline_latex(session: AsyncSession, project: ResearchProject) -> bytes:
    steps = _steps(project)
    sources = {s["number"]: s for s in steps["outline"]["sources"]}
    doc_ids = list(
        dict.fromkeys(
            uuid.UUID(s["document"]["id"]) for s in sources.values() if s["document"].get("id")
        )
    )
    try:
        references = await org.references_for(session, project.user_id, doc_ids)
    except Exception:  # a cited paper was deleted: cite the remaining ones
        references = []
    keys = dict(zip(doc_ids, citation_keys(references), strict=False)) if references else {}

    def cite(match: re.Match[str]) -> str:
        numbers = [int(n) for n in re.findall(r"\d+", match.group(0))]
        found = []
        for n in numbers:
            source = sources.get(n)
            key = (
                keys.get(uuid.UUID(source["document"]["id"]))
                if source and source["document"].get("id")
                else None
            )
            if key and key not in found:
                found.append(key)
        return f"~\\cite{{{','.join(found)}}}" if found else ""

    def body(text: str) -> str:
        out = []
        for part in re.split(r"\n\s*\n", text.strip()):
            lines = [line.strip() for line in part.splitlines() if line.strip()]
            if lines and all(line.startswith("- ") for line in lines):
                items = "\n".join(f"  \\item {_render(line[2:])}" for line in lines)
                out.append(f"\\begin{{itemize}}\n{items}\n\\end{{itemize}}")
            elif lines:
                out.append(_render(" ".join(lines)))
        return "\n\n".join(out)

    def _render(text: str) -> str:
        # Escape everything, then restore citations and bold.
        pieces = re.split(r"((?:\[\d+\])+|\*\*.+?\*\*)", text)
        rendered = []
        for piece in pieces:
            if _CITE_RUN.fullmatch(piece or ""):
                rendered.append(_CITE_RUN.sub(cite, piece))
            elif piece.startswith("**") and piece.endswith("**") and len(piece) > 4:
                rendered.append(f"\\textbf{{{_latex(piece[2:-2])}}}")
            else:
                rendered.append(_latex(piece))
        return "".join(rendered).replace(" ~\\cite", "~\\cite")

    sections = "\n\n".join(
        f"\\section{{{_latex(s['title'])}}}\n{body(s.get('text') or '')}"
        for s in steps["outline"]["sections"]
    )
    tex = (
        "\\documentclass{article}\n\\usepackage[utf8]{inputenc}\n\\usepackage{hyperref}\n\n"
        f"\\title{{{_latex(project.title)}}}\n\\date{{}}\n\n\\begin{{document}}\n\\maketitle\n\n"
        f"% Research question: {project.question.replace(chr(10), ' ')}\n\n"
        f"{sections}\n\n\\bibliographystyle{{plain}}\n\\bibliography{{references}}\n\\end{{document}}\n"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("main.tex", tex)
        archive.writestr("references.bib", bibtex(references) if references else "")
    return buffer.getvalue()
