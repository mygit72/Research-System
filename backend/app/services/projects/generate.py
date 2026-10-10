"""The two project steps that use the language model, both grounded in the user's papers.

- **Questions**: passages found for the idea → the model proposes research questions, each
  ending with the passages it builds on; a question citing nothing is dropped, and each
  kept question is checked against its passages like any other statement.
- **Outline**: the introduction is written from passages found for the chosen question and
  gap (cited, checked); related work is copied from the project's literature review with
  its citations renumbered; method, experiments and conclusion are scaffolds built from the
  user's own plan (marked as such — nothing is invented about results).
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models.project import ResearchProject
from app.models.report import ReportStatus, ResearchReport
from app.services.analysis.digests import SourceBook
from app.services.analysis.writing import Writer, evidence_blocks, normalize_citations
from app.services.llm import INSUFFICIENT, GenerationParams, Message, get_llm
from app.services.projects.service import _steps, project_papers
from app.services.rag.citations import split_claims, validate_citations
from app.services.rag.context import select_context
from app.services.rag.pipeline import get_verifier
from app.services.retrieval.service import SearchFilters, SearchRequest, search
from app.services.retrieval.types import SearchMode

QUESTIONS_SYSTEM = f"""You help a researcher turn an idea into research questions, using ONLY the numbered evidence passages from their papers.

Rules:
- Propose 3 to 5 specific, answerable research questions that build on the evidence and fit the idea.
- Write each question as a full sentence ending with a question mark, then the numbers of the passages it builds on in square brackets. One question per line.
- Do not invent results, datasets or papers that are not in the evidence.
- If the evidence is unrelated to the idea, reply with exactly: "{INSUFFICIENT}\""""

INTRO_SYSTEM = f"""You are writing the introduction of a research paper using ONLY the numbered evidence passages from the author's reading.

Rules:
- Write one paragraph of 4 to 6 sentences: the context, what prior work did, and the gap the research question addresses.
- End every sentence that states a fact with the number of the passage that supports it, placed just before the full stop, like this: "<statement> [2]." Use only numbers that appear in the evidence.
- Do not claim results for the author's own work, and do not invent anything.
- If the evidence does not cover it, reply with exactly: "{INSUFFICIENT}\""""

_CITE = re.compile(r"\[(\d+)\]")


def related_passages(
    question: str, numbers: list[int], book: SourceBook, top: int = 2
) -> list[int]:
    """Passages sharing most of the question's terms (stemmed, stopwords removed)."""
    from app.services.retrieval.text import analyze

    terms = set(analyze(question))
    if not terms:
        return []
    scored = sorted(
        ((len(terms & set(analyze(book.text(n)))) / len(terms), n) for n in numbers),
        key=lambda s: (-s[0], s[1]),
    )
    return [n for score, n in scored[:top] if score >= RELATED_MIN_OVERLAP]


RELATED_MIN_OVERLAP = 0.3


async def _evidence(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    project: ResearchProject,
    query: str,
    book: SourceBook,
    *,
    only: list[uuid.UUID] | None = None,
    max_passages: int | None = None,
) -> list[int]:
    from app.services.analysis.deep_research import _source

    async with session_factory() as session:
        scope = only or (
            await project_papers(session, settings, project) if project.collection_id else None
        )
        outcome = await search(
            session,
            settings,
            project.user_id,
            SearchRequest(
                query[:500],
                SearchMode.HYBRID,
                SearchFilters(document_ids=scope) if scope else SearchFilters(),
                limit=settings.rerank_candidates,
            ),
        )
    selection = select_context(
        outcome.results,
        settings.context_token_budget,
        max_passages or settings.context_max_passages,
        settings.context_min_relevance,
    )
    return [book.add(_source(e.result)) for e in selection.evidence]


MAX_COVERED = 8  # papers given their own search when the main one missed them
PASSAGES_PER_MISSED_PAPER = 2


async def _cover_every_paper(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    project: ResearchProject,
    query: str,
    book: SourceBook,
    numbers: list[int],
) -> list[int]:
    """One search over the whole project lets a single paper crowd out the others. Any project
    paper with no passage yet gets its own search (its best passages only), so the introduction
    is written from all of them."""
    async with session_factory() as session:
        papers = await project_papers(session, settings, project)
    covered = {book.items[n - 1]["document"]["id"] for n in numbers}
    extra: list[int] = []
    for paper in [p for p in papers if str(p) not in covered][:MAX_COVERED]:
        extra += await _evidence(
            session_factory,
            settings,
            project,
            query,
            book,
            only=[paper],
            max_passages=PASSAGES_PER_MISSED_PAPER,
        )
    return list(dict.fromkeys([*numbers, *extra]))


def _writer(settings: Settings, book: SourceBook) -> Writer:
    return Writer(
        get_llm(settings),
        GenerationParams(settings.summary_max_tokens, settings.llm_temperature),
        get_verifier(settings),
        book,
    )


async def suggest_questions(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    project: ResearchProject,
    report: Any,
) -> dict[str, Any]:
    book = SourceBook()
    await report("searching", 0.1, "Finding passages related to your idea")
    numbers = await _evidence(session_factory, settings, project, project.idea, book)
    if not numbers:
        return {
            "suggestions": [],
            "sources": [],
            "note": "None of your papers relate to this idea yet.",
        }
    writer = _writer(settings, book)
    await report("writing", 0.4, "Suggesting research questions")
    # Questions aren't claims, so they aren't entailment-checked; each must still cite the
    # passages it builds on (citations to passages it wasn't given are dropped).
    reply = await writer.generate(
        [
            Message("system", QUESTIONS_SYSTEM),
            Message(
                "user",
                f"Evidence:\n{evidence_blocks(book, numbers)}\n\nQuestion: The researcher's "
                f"idea: {project.idea}\nWhich research questions follow from it?",
            ),
        ],
        "questions",
    )
    text = validate_citations(normalize_citations(reply, len(book.items)), len(book.items)).text
    suggestions = []
    if not text.startswith(INSUFFICIENT[:40]):
        for claim in split_claims(text):
            cited = [n for n in claim.citations if n in numbers]
            question = re.sub(r"^\d+[.)]\s*", "", claim.text.strip(" -•*"))
            if len(question.split()) < 5:
                continue
            # Measured with qwen2.5:3b: a format template ("<question>? [2][4]") was filled
            # with numbers ("1? [1][2][4]" ×5); without it the questions are good but uncited.
            # So the model's citations are kept when given, else the system links the passages
            # the question overlaps most with — labelled as such.
            status = "cited"
            if not cited:
                cited, status = related_passages(question, numbers, book), "related"
            if not cited:
                continue  # a suggestion must show which passages it builds on
            suggestions.append(
                {
                    "text": question,
                    "citations": cited,
                    "papers": sorted({book.title(n) for n in cited}),
                    "status": status,
                }
            )
    return {
        "suggestions": suggestions[:6],
        "sources": [
            s for s in book.items if s["number"] in {n for q in suggestions for n in q["citations"]}
        ],
        "model": writer.model,
    }


def _renumber(text: str, mapping: dict[int, int]) -> str:
    return _CITE.sub(
        lambda m: f"[{mapping[int(m.group(1))]}]" if int(m.group(1)) in mapping else "", text
    )


async def suggest_outline(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    project: ResearchProject,
    report: Any,
) -> dict[str, Any]:
    steps = _steps(project)
    book = SourceBook()
    gap = steps["gaps"].get("chosen") or {}
    sections: list[dict[str, Any]] = []

    # Introduction: written from passages, cited and checked.
    await report("searching", 0.1, "Finding passages for the introduction")
    intro_query = f"{project.question} {gap.get('title', '')}"
    numbers = await _evidence(session_factory, settings, project, intro_query, book)
    numbers = await _cover_every_paper(
        session_factory, settings, project, intro_query, book, numbers
    )
    writer = _writer(settings, book)
    await report("writing", 0.35, "Writing the introduction")
    intro = await writer.section(
        "introduction",
        "Introduction",
        f"Research question: {project.question}\n"
        + (f"Gap it addresses: {gap.get('title')}: {gap.get('text', '')}\n" if gap else "")
        + "Write the introduction.",
        numbers,
        system=INTRO_SYSTEM,
    )
    sections.append(intro)

    # Related work: the literature review's theme paragraphs, citations renumbered.
    await report("writing", 0.7, "Taking related work from your review")
    related_text, related_cites = "", []
    report_id = steps["background"].get("report_id")
    if report_id:
        async with session_factory() as session:
            review = await session.get(ResearchReport, uuid.UUID(report_id))
        if review is not None and review.status == ReportStatus.READY:
            sources = {s["number"]: s for s in review.sources}
            paragraphs = []
            for section in review.sections:
                if (
                    section.get("kind") == "text"
                    and section.get("key", "").startswith("theme-")
                    and section.get("text")
                ):
                    used = sorted({int(n) for n in _CITE.findall(section["text"])} & set(sources))
                    mapping = {n: book.add(sources[n]) for n in used}
                    paragraphs.append(
                        f"**{section['title']}.** {_renumber(section['text'], mapping)}"
                    )
                    related_cites += list(mapping.values())
            cited_docs = {book.items[n - 1]["document"]["id"] for n in related_cites}
            lines, line_cites = await _uncited_papers(
                session_factory, settings, project, cited_docs, book
            )
            if lines:
                paragraphs.append("**Also in this project.**\n\n" + "\n".join(lines))
                related_cites += line_cites
            related_text = "\n\n".join(paragraphs)
    sections.append(
        {
            "key": "related_work",
            "title": "Related work",
            "kind": "text",
            "text": related_text,
            "citations": sorted(set(related_cites)),
            "claims": [],
            "status": "derived" if related_text else "missing",
            "label": "From your literature review"
            if related_text
            else "Generate the background review first",
            "origin": "derived",
        }
    )

    # Method / experiments / conclusion: scaffolds from the user's own plan.
    chosen = steps["methods"]["chosen"]
    method_lines = [f"- **Hypothesis:** {project.hypothesis or '(write your hypothesis)'}"]
    for label, key in (
        ("Builds on", "methods"),
        ("Baselines", "baselines"),
        ("Datasets", "datasets"),
        ("Metrics", "metrics"),
    ):
        if chosen.get(key):
            method_lines.append(f"- **{label}:** {', '.join(chosen[key])}")
    sections.append(_scaffold("method", "Method", "\n".join(method_lines)))
    experiment_lines = [
        f"- **{item['title']}** — {item['setup']}; metrics: {', '.join(item.get('metrics', []))}"
        for item in steps["experiments"]["items"]
    ] or ["- (plan your experiments in the Experiments step)"]
    sections.append(_scaffold("experiments", "Experiments", "\n".join(experiment_lines)))
    sections.append(
        _scaffold(
            "conclusion",
            "Conclusion",
            "- Answer the research question with your results.\n- State the limitations.\n- Future work.",
        )
    )
    return {"sections": sections, "sources": book.items, "model": writer.model}


STATEMENT_ORDER = ("contribution", "takeaway", "problem", "method", "results")


def _best_statement(digest: Any) -> Any:
    """The paper's best checked statement: what it contributes before what it did, and a fully
    supported one before a partly supported one."""
    for wanted in ("supported", "partial"):
        for fld in STATEMENT_ORDER:
            for statement in digest.of(fld):
                if statement.status == wanted:
                    return statement
    return None


async def _uncited_papers(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    project: ResearchProject,
    cited_docs: set[str],
    book: SourceBook,
) -> tuple[list[str], list[int]]:
    """A line for every project paper the review text doesn't mention: its checked contribution
    statement with its passage. A paper with no statement that passed the check is named but not
    cited — a citation has to point at a passage that supports something."""
    from app.models.document import Document
    from app.services.analysis.digests import digest_from_summary
    from app.services.summaries.service import last_ready_summary

    async with session_factory() as session:
        papers = await project_papers(session, settings, project)
        lines: list[str] = []
        cites: list[int] = []
        for paper_id in papers:
            if str(paper_id) in cited_docs:
                continue
            document = await session.get(Document, paper_id)
            if document is None:
                continue
            summary = await last_ready_summary(session, paper_id)
            digest = digest_from_summary(document, summary, True) if summary else None
            statement = _best_statement(digest) if digest else None
            year = f" ({document.year})" if document.year else ""
            if statement is None:
                lines.append(
                    f"- **{document.title}{year}.** No statement from this paper passed the check, "
                    "so it isn't cited here."
                )
                continue
            numbers = book.cite(statement)[:2]
            cites += numbers
            marks = "".join(f"[{n}]" for n in numbers)
            partly = (
                " *(only partly supported by its passage)*"
                if statement.status != "supported"
                else ""
            )
            lines.append(f"- **{document.title}{year}.** {statement.text} {marks}{partly}")
    return lines, cites


def _scaffold(key: str, title: str, text: str) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "kind": "text",
        "text": text,
        "citations": [],
        "claims": [],
        "status": "scaffold",
        "label": "Scaffold from your plan — yours to write",
        "origin": "scaffold",
    }


async def run_step(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    project_id: uuid.UUID,
    step: str,
    report: Any,
) -> dict[str, Any]:
    async with session_factory() as session:
        project = await session.get(ResearchProject, project_id)
        if project is None:
            return {"status": "deleted"}
        session.expunge(project)
    try:
        if step == "questions":
            result = await suggest_questions(session_factory, settings, project, report)
        else:
            result = await suggest_outline(session_factory, settings, project, report)
        error = None
    except Exception as exc:  # stored on the step so the page can say what happened
        result, error = (
            {},
            getattr(exc, "user_message", None) or getattr(exc, "message", None) or str(exc),
        )
    async with session_factory() as session:
        row = await session.get(ResearchProject, project_id)
        if row is None:
            return {"status": "deleted"}
        steps = _steps(row)
        steps[step] = {
            **steps[step],
            **result,
            "status": "failed" if error else "ready",
            "error": error,
        }
        row.steps = steps
        await session.commit()
    return {
        "step": step,
        "error": error,
        "items": len(result.get("suggestions", result.get("sections", []))),
    }
