"""Research Project Builder: from an idea to a plan and a paper outline.

Steps (each keeps the system's suggestions apart from the user's choices):

1. **Questions** — research questions suggested from the idea and the passages of the
   user's papers it relates to (cited and checked; background job).
2. **Background** — a literature review (Phase 11) of the project's papers.
3. **Gap & hypothesis** — a research-gaps report (Phase 11); the user picks a gap and writes
   the hypothesis.
4. **Methods** — datasets, models / baselines, methods and metrics that the project's papers
   actually use, counted and linked to the papers (knowledge layer; no model involved).
5. **Experiments & milestones** — a comparison matrix built from the chosen method plan,
   ablation and analysis slots, and milestones spread up to a deadline (deterministic).
6. **Outline** — a paper outline: the introduction written from passages (cited, checked),
   related work taken from the review (with its citations), method and experiments
   sections built from the user's own plan.

The project's papers are its collection, or the papers found for its question / idea.
"""

from __future__ import annotations

import copy
import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.job import Job
from app.models.project import ResearchProject
from app.models.report import ReportKind, ReportStatus, ResearchReport
from app.services import organization as org
from app.services.analysis.service import request_report
from app.services.jobs import JobService
from app.services.knowledge.entities import ensure_entities
from app.services.knowledge.library import load_library
from app.services.summaries.service import ensure_llm_ready

PROJECT_JOB = "project.suggest"
LLM_STEPS = ("questions", "outline")
MAX_SUGGESTIONS = 12
DEFAULT_MILESTONES = [
    "Finish the literature review",
    "Prepare data and baselines",
    "Run the main experiments",
    "Run ablations and analysis",
    "Write the paper",
    "Internal review and submission",
]


def empty_steps() -> dict[str, Any]:
    return {
        "questions": {"status": "idle", "suggestions": [], "sources": [], "error": None},
        "background": {"report_id": None},
        "gaps": {"report_id": None, "chosen": None},
        "methods": {
            "suggestions": {},
            "chosen": {"datasets": [], "baselines": [], "methods": [], "metrics": []},
        },
        "experiments": {"items": [], "milestones": [], "deadline": None},
        "outline": {"status": "idle", "sections": [], "sources": [], "error": None},
    }


def _steps(project: ResearchProject) -> dict[str, Any]:
    """A deep copy with defaults filled in. Edit the copy and assign it back: mutating the
    stored JSON in place would go unnoticed by the ORM (its "before" value would change too)."""
    steps = empty_steps()
    for key, value in copy.deepcopy(project.steps or {}).items():
        steps[key] = {**steps.get(key, {}), **value}
    return steps


async def create_project(
    session: AsyncSession,
    user_id: uuid.UUID,
    idea: str,
    title: str | None,
    collection_id: uuid.UUID | None,
) -> ResearchProject:
    idea = idea.strip()
    if len(idea.split()) < 3:
        raise ValidationError("Describe your idea in at least a few words.")
    if collection_id is not None:
        await org.get_collection(session, user_id, collection_id)
    project = ResearchProject(
        user_id=user_id,
        title=(title or idea.split(".")[0])[:300].strip(),
        idea=idea,
        collection_id=collection_id,
        steps=empty_steps(),
    )
    session.add(project)
    await session.flush()
    return project


async def get_project(
    session: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID
) -> ResearchProject:
    project = await session.get(ResearchProject, project_id)
    if project is None or project.user_id != user_id:
        raise NotFoundError("Project not found.")
    return project


async def list_projects(session: AsyncSession, user_id: uuid.UUID) -> list[ResearchProject]:
    rows = await session.execute(
        select(ResearchProject)
        .where(ResearchProject.user_id == user_id)
        .order_by(ResearchProject.updated_at.desc())
    )
    return list(rows.scalars())


async def linked_reports(
    session: AsyncSession, project: ResearchProject
) -> dict[str, ResearchReport | None]:
    steps = _steps(project)
    out: dict[str, ResearchReport | None] = {}
    for step in ("background", "gaps"):
        report_id = steps[step].get("report_id")
        report = await session.get(ResearchReport, uuid.UUID(report_id)) if report_id else None
        out[step] = report if report is not None and report.user_id == project.user_id else None
    return out


async def job_progress(session: AsyncSession, project: ResearchProject) -> dict[str, Any] | None:
    if project.job_id is None:
        return None
    job = await session.get(Job, project.job_id)
    if job is None or job.status in ("succeeded", "failed"):
        return None
    return {"stage": job.stage, "detail": job.stage_detail, "progress": job.progress}


def completion(
    project: ResearchProject, reports: dict[str, ResearchReport | None]
) -> dict[str, bool]:
    steps = _steps(project)
    chosen = steps["methods"]["chosen"]
    background = reports.get("background")
    return {
        "questions": bool(project.question.strip()),
        "background": background is not None and background.status == ReportStatus.READY,
        "gaps": bool(steps["gaps"].get("chosen")) and bool(project.hypothesis.strip()),
        "methods": any(chosen.get(k) for k in ("datasets", "baselines", "methods", "metrics")),
        "experiments": bool(steps["experiments"]["items"]),
        "outline": bool(steps["outline"]["sections"]),
    }


# --- guidance ------------------------------------------------------------------------------------

MIN_PAPERS = 4  # fewer and a review has nothing to group and gaps nothing to cross-check


async def scope_size(
    session: AsyncSession, project: ResearchProject, reports: dict[str, ResearchReport | None]
) -> int | None:
    """How many papers the project draws on, when that is known without searching."""
    if project.collection_id is not None:
        return len(await org.collection_document_ids(session, project.collection_id))
    background = reports.get("background")
    return (
        len(background.document_ids) if background is not None and background.document_ids else None
    )


def guidance(project: ResearchProject, done: dict[str, bool], papers: int | None) -> dict[str, Any]:
    """What to do next, and what would make the suggestions better. Deterministic."""
    notes: list[str] = []
    if project.collection_id is None:
        notes.append(
            "Link a collection of papers to this project: every suggestion comes from your own "
            "library, and a collection keeps them to the papers you chose."
        )
    elif papers is not None and papers < MIN_PAPERS:
        notes.append(
            f"The project has {papers} paper{'s' if papers != 1 else ''}. Reviews and gaps need "
            f"several papers per theme — add {MIN_PAPERS - papers} or more related papers to its "
            "collection for a more useful background."
        )
    prompts = {
        "questions": "Write your research question, or ask for suggestions and pick one.",
        "background": "Run the background review to see what the papers say and where they differ.",
        "gaps": "Run the gaps report, pick the gap you will address and write your hypothesis.",
        "methods": "Choose the datasets, baselines, methods and metrics for your plan.",
        "experiments": "Plan the experiments and set a deadline for the milestones.",
        "outline": "Draft the paper outline.",
    }
    step = next((s for s in prompts if not done.get(s)), None)
    return {
        "next_step": {"step": step, "message": prompts[step]}
        if step
        else {"step": None, "message": "Every step is done — review the outline and export it."},
        "notes": notes,
    }


# --- scope ---------------------------------------------------------------------------------------


async def project_papers(
    session: AsyncSession, settings: Settings, project: ResearchProject
) -> list[uuid.UUID]:
    """The collection's papers, else the background review's, else papers found for the
    question / idea (keyword-matching search, as for reviews)."""
    from app.services.analysis.reports import choose_papers

    if project.collection_id is not None:
        return await org.collection_document_ids(session, project.collection_id)
    reports = await linked_reports(session, project)
    background = reports.get("background")
    if background is not None and background.document_ids:
        return [uuid.UUID(d) for d in background.document_ids]
    topic = project.question.strip() or project.idea
    try:
        chosen, _ = await choose_papers(session, settings, project.user_id, topic, [], None, 16)
    except ValidationError:
        return []
    return chosen


# --- step 2 / 3: reports -------------------------------------------------------------------------


async def start_report(
    session: AsyncSession,
    settings: Settings,
    jobs: JobService,
    project: ResearchProject,
    step: str,
) -> ResearchReport:
    """Background → literature review; gaps → research-gaps report, over the project's papers."""
    kind = ReportKind.REVIEW if step == "background" else ReportKind.GAPS
    topic = project.question.strip() or project.idea
    if project.collection_id is not None:
        report = await request_report(
            session, settings, jobs, project.user_id, kind,
            query=topic[:300], collection_id=project.collection_id,
        )  # fmt: skip
    else:
        papers = await project_papers(session, settings, project)
        if len(papers) < (2 if kind == ReportKind.REVIEW else 1):
            raise ConflictError(
                "Not enough of your papers match this project yet.",
                hint="Add papers to a collection and link it to the project, or upload more "
                "papers on the topic.",
            )
        report = await request_report(
            session, settings, jobs, project.user_id, kind,
            query=topic[:300], document_ids=papers,
        )  # fmt: skip
    steps = _steps(project)
    steps[step] = {**steps[step], "report_id": str(report.id)}
    if step == "gaps":
        steps["gaps"]["chosen"] = None
    project.steps = steps
    return report


# --- step 4: methods (knowledge layer) -----------------------------------------------------------


async def suggest_methods(
    session: AsyncSession, settings: Settings, project: ResearchProject
) -> dict[str, list[dict[str, Any]]]:
    """What the project's papers actually use, most used first, with the papers."""
    papers = set(await project_papers(session, settings, project))
    await ensure_entities(session, project.user_id)
    library = await load_library(session, project.user_id)
    groups: dict[str, Counter[uuid.UUID]] = {
        k: Counter() for k in ("dataset", "model", "method", "metric", "task")
    }
    proposed: Counter[uuid.UUID] = Counter()
    users: dict[uuid.UUID, list[uuid.UUID]] = {}
    for link in library.links:
        if link.document_id not in papers or link.relation not in ("uses", "proposes"):
            continue
        entity = library.entities[link.entity_id]
        groups[entity.type][entity.id] += 1
        users.setdefault(entity.id, []).append(link.document_id)
        if link.relation == "proposes":
            proposed[entity.id] += 1
    out: dict[str, list[dict[str, Any]]] = {}
    for kind, counts in groups.items():
        out[kind] = [
            {
                "entity_id": str(entity_id),
                "name": library.entities[entity_id].name,
                "papers": [
                    {"id": str(d), "title": library.papers[d].title, "year": library.papers[d].year}
                    for d in users[entity_id]
                    if d in library.papers
                ],
                "count": count,
                "proposed_by": proposed[entity_id],
                "info": library.entities[entity_id].info,
            }
            for entity_id, count in counts.most_common(MAX_SUGGESTIONS)
        ]
    steps = _steps(project)
    steps["methods"]["suggestions"] = out
    steps["methods"]["paper_count"] = len(papers)
    project.steps = steps
    return out


# --- step 5: experiments & milestones (deterministic) --------------------------------------------


def plan_experiments(project: ResearchProject) -> list[dict[str, Any]]:
    """A comparison per dataset against the chosen baselines, plus ablation / analysis slots."""
    chosen = _steps(project)["methods"]["chosen"]
    datasets = chosen.get("datasets") or ["(choose a dataset)"]
    baselines = chosen.get("baselines") or []
    metrics = chosen.get("metrics") or ["(choose a metric)"]
    approach = ", ".join(chosen.get("methods") or []) or "your approach"
    versus = ", ".join(baselines) or "the strongest baseline from your papers"
    items = [
        {
            "key": f"main-{i + 1}",
            "kind": "main",
            "title": f"Main comparison on {dataset}",
            "goal": f"Test the hypothesis: {project.hypothesis.strip()}"
            if project.hypothesis.strip()
            else "Test the hypothesis.",
            "setup": f"{approach} vs. {versus} on {dataset}",
            "metrics": metrics,
            "notes": "",
        }
        for i, dataset in enumerate(datasets)
    ]
    items.append(
        {
            "key": "ablation-1",
            "kind": "ablation",
            "title": "Ablation",
            "goal": "Which part of the approach is responsible for the effect?",
            "setup": f"Remove or replace one component of {approach} at a time, on {datasets[0]}",
            "metrics": metrics,
            "notes": "",
        }
    )
    items.append(
        {
            "key": "analysis-1",
            "kind": "analysis",
            "title": "Error and robustness analysis",
            "goal": "Where does the approach still fail?",
            "setup": "Break results down by input type / length / domain; inspect failures.",
            "metrics": metrics,
            "notes": "",
        }
    )
    return items


def plan_milestones(deadline: date, today: date | None = None) -> list[dict[str, Any]]:
    today = today or datetime.now(UTC).date()
    if deadline <= today:
        raise ValidationError("The deadline must be in the future.")
    span = (deadline - today).days
    # Weights: the main experiments and writing take the longest.
    weights = [2, 2, 3, 2, 3, 1]
    total = sum(weights)
    milestones, elapsed = [], 0
    for title, weight in zip(DEFAULT_MILESTONES, weights, strict=True):
        elapsed += weight
        due = today + timedelta(days=round(span * elapsed / total))
        milestones.append({"title": title, "due": due.isoformat(), "done": False})
    return milestones


# --- edits ---------------------------------------------------------------------------------------


def apply_update(project: ResearchProject, changes: dict[str, Any]) -> None:
    steps = _steps(project)
    for field in ("title", "idea", "question", "hypothesis"):
        if changes.get(field) is not None:
            value = str(changes[field]).strip()
            if field == "title" and not value:
                raise ValidationError("The title can't be empty.")
            setattr(project, field, value[:300] if field == "title" else value)
    if "collection_id" in changes:
        project.collection_id = changes["collection_id"]
    if changes.get("gap") is not None:
        steps["gaps"]["chosen"] = changes["gap"] or None
    if changes.get("methods") is not None:
        steps["methods"]["chosen"] = {
            k: [str(v).strip() for v in changes["methods"].get(k, []) if str(v).strip()][:20]
            for k in ("datasets", "baselines", "methods", "metrics")
        }
    if changes.get("experiments") is not None:
        steps["experiments"]["items"] = changes["experiments"][:30]
    if changes.get("milestones") is not None:
        steps["experiments"]["milestones"] = changes["milestones"][:20]
    if changes.get("outline") is not None:
        by_key = {s["key"]: s for s in steps["outline"]["sections"]}
        for edit in changes["outline"]:
            section = by_key.get(edit["key"])
            if section is None:
                raise ValidationError(f"There's no outline section “{edit['key']}”.")
            if edit.get("text") is not None and edit["text"] != section.get("text"):
                section["text"] = edit["text"]
                section["edited"] = True
                section["label"] = "Edited by you"
        steps["outline"]["sections"] = list(by_key.values())
    project.steps = steps


async def request_suggestions(
    session: AsyncSession, settings: Settings, jobs: JobService, project: ResearchProject, step: str
) -> None:
    if step not in LLM_STEPS:
        raise ValidationError(f"Unknown step “{step}”.")
    if step == "outline" and not project.question.strip():
        raise ValidationError("Choose a research question first.")
    steps = _steps(project)
    if steps[step]["status"] == "running":
        return
    await ensure_llm_ready(settings)
    steps[step] = {**steps[step], "status": "running", "error": None}
    project.steps = steps
    job = await jobs.enqueue(
        project.user_id,
        PROJECT_JOB,
        payload={"project_id": str(project.id), "step": step},
        subject_type="project",
        subject_id=project.id,
    )
    project.job_id = job.id
