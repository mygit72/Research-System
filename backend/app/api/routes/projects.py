"""Research Project Builder: a guided plan from an idea to a paper outline."""

from __future__ import annotations

import ast
import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, JobServiceDep, SettingsDep
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.document import Chunk, Document
from app.models.project import ResearchProject
from app.schemas.project import (
    AttentionExperimentRequest,
    ClaimEvidenceRequest,
    ClaimStressTestRequest,
    CodeFileEdit,
    ExperimentPlanRequest,
    PaperRunMatchRequest,
    PredictionAnalysisRequest,
    ProjectCreate,
    ProjectGuidance,
    ProjectOut,
    ProjectSummary,
    ProjectUpdate,
    ResultsAnalysisRequest,
)
from app.schemas.report import ReportSummary
from app.schemas.summary import SummaryProgress
from app.services import retrieval
from app.services.projects import codegen, export, project_runner
from app.services.projects.experiment_runner import run_claim_stress_test, run_reference_attention
from app.services.projects.guide import step_guide
from app.services.projects.paper_run_match import assess_paper_run_match
from app.services.projects.prediction_analysis import analyze_predictions_jsonl
from app.services.projects.results_analysis import analyze_results_csv
from app.services.projects.service import (
    _steps,
    apply_update,
    completion,
    create_project,
    get_project,
    guidance,
    job_progress,
    linked_reports,
    list_projects,
    plan_experiments,
    plan_milestones,
    project_papers,
    request_suggestions,
    scope_size,
    start_report,
    suggest_methods,
)
from app.services.retrieval import SearchFilters, SearchMode, SearchRequest

router = APIRouter(prefix="/projects", tags=["projects"])


async def _out(db: DbSession, project: ResearchProject) -> ProjectOut:
    await db.flush()
    await db.refresh(project)
    reports = await linked_reports(db, project)
    out = ProjectOut.model_validate(project)
    out.steps = _steps(project)
    out.completion = completion(project, reports)
    out.guidance = ProjectGuidance(
        **guidance(project, out.completion, await scope_size(db, project, reports))
    )
    out.guidance = ProjectGuidance(
        **guidance(project, out.completion, await scope_size(db, project, reports))
    )
    out.reports = {k: ReportSummary.model_validate(r) if r else None for k, r in reports.items()}
    state = await job_progress(db, project)
    out.progress = SummaryProgress(**state) if state else None
    return out


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create(body: ProjectCreate, user: CurrentUser, db: DbSession) -> ProjectOut:
    return await _out(
        db, await create_project(db, user.id, body.idea, body.title, body.collection_id)
    )


@router.get("", response_model=list[ProjectSummary])
async def recent(user: CurrentUser, db: DbSession) -> list[ProjectSummary]:
    return [ProjectSummary.model_validate(p) for p in await list_projects(db, user.id)]


@router.get("/{project_id}", response_model=ProjectOut)
async def read(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ProjectOut:
    return await _out(db, await get_project(db, user.id, project_id))


@router.patch("/{project_id}", response_model=ProjectOut, summary="Save choices and edits")
async def update(
    project_id: uuid.UUID, body: ProjectUpdate, user: CurrentUser, db: DbSession
) -> ProjectOut:
    from app.services import organization as org

    project = await get_project(db, user.id, project_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("collection_id") is not None:
        await org.get_collection(db, user.id, changes["collection_id"])
    apply_update(project, changes)
    return await _out(db, project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    await db.delete(await get_project(db, user.id, project_id))


@router.post(
    "/{project_id}/suggest/{step}",
    response_model=ProjectOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Suggest research questions, draft the paper outline, or draft the starter code's TODO stubs (background job)",
)
async def suggest(
    project_id: uuid.UUID,
    step: Literal["questions", "outline", "code"],
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
    jobs: JobServiceDep,
) -> ProjectOut:
    project = await get_project(db, user.id, project_id)
    await request_suggestions(db, settings, jobs, project, step)
    return await _out(db, project)


@router.post(
    "/{project_id}/reports/{step}",
    response_model=ProjectOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start the background review or the gaps report for the project's papers",
)
async def start(
    project_id: uuid.UUID,
    step: Literal["background", "gaps"],
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
    jobs: JobServiceDep,
) -> ProjectOut:
    project = await get_project(db, user.id, project_id)
    await start_report(db, settings, jobs, project, step)
    return await _out(db, project)


@router.post(
    "/{project_id}/methods",
    response_model=ProjectOut,
    summary="Datasets, models, methods and metrics the project's papers use",
)
async def methods(
    project_id: uuid.UUID, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> ProjectOut:
    project = await get_project(db, user.id, project_id)
    await suggest_methods(db, settings, project)
    return await _out(db, project)


@router.post(
    "/{project_id}/experiments",
    response_model=ProjectOut,
    summary="Plan experiments from the method plan, and milestones up to a deadline",
)
async def experiments(
    project_id: uuid.UUID, body: ExperimentPlanRequest, user: CurrentUser, db: DbSession
) -> ProjectOut:
    project = await get_project(db, user.id, project_id)
    steps = _steps(project)
    changes: dict[str, object] = {}
    if body.replace or not steps["experiments"]["items"]:
        changes["experiments"] = plan_experiments(project)
    if body.deadline is not None:
        changes["milestones"] = plan_milestones(body.deadline)
    apply_update(project, changes)
    if body.deadline is not None:
        steps = _steps(project)
        steps["experiments"]["deadline"] = body.deadline.isoformat()
        project.steps = steps
    return await _out(db, project)


@router.post(
    "/{project_id}/experiments/run-attention",
    summary="Run the fixed reference attention comparison and save its evidence snapshot",
)
async def run_attention_experiment(
    project_id: uuid.UUID,
    body: AttentionExperimentRequest,
    user: CurrentUser,
    db: DbSession,
) -> dict[str, Any]:
    project = await get_project(db, user.id, project_id)
    model_draft = _steps(project)["code"].get("drafts", {}).get("model")
    if not model_draft or model_draft.get("status") != "drafted":
        raise ConflictError("Generate a paper-grounded model draft before running this comparison.")

    result = run_reference_attention(body.score_divisor)
    result.update(
        {
            "id": str(uuid.uuid4()),
            "created_at": datetime.now(UTC).isoformat(),
            "question": project.question.strip() or project.idea,
            "hypothesis": project.hypothesis.strip(),
            "draft_model": model_draft.get("model"),
            "evidence_sources": model_draft.get("sources", []),
        }
    )
    steps = _steps(project)
    steps["experiments"]["reference_run"] = result
    project.steps = steps
    await db.flush()
    return result


@router.post(
    "/{project_id}/experiments/claim-evidence",
    summary="Find paper passages for a claim within this project's paper scope",
)
async def claim_evidence(
    project_id: uuid.UUID,
    body: ClaimEvidenceRequest,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
) -> dict[str, Any]:
    project = await get_project(db, user.id, project_id)
    paper_ids = await project_papers(db, settings, project)
    if not paper_ids:
        raise ConflictError(
            "There are no papers in this project's scope yet.",
            hint="Link a paper collection or add papers related to your research question.",
        )
    outcome = await retrieval.search(
        db,
        settings,
        user.id,
        SearchRequest(
            query=body.claim,
            mode=SearchMode.HYBRID,
            filters=SearchFilters(document_ids=paper_ids),
            limit=8,
        ),
    )
    return {
        "claim": body.claim.strip(),
        "status": outcome.status,
        "paper_count": outcome.searched_papers,
        "passages": [
            {
                "chunk_id": str(hit.chunk.id),
                "document_id": str(hit.document.id),
                "title": hit.document.title,
                "year": hit.document.year,
                "section_title": hit.chunk.section_title,
                "page_start": hit.chunk.page_start,
                "page_end": hit.chunk.page_end,
                "char_start": hit.chunk.char_start,
                "boxes": hit.chunk.boxes,
                "quote": hit.chunk.text[:1800],
            }
            # Claims should lead with a body passage where possible. Abstracts are useful
            # orientation, but they are weaker evidence for a reproducible experiment.
            for hit in sorted(
                outcome.results,
                key=lambda hit: (hit.chunk.section_kind in {"abstract", "metadata"}, hit.rank),
            )
        ],
    }


@router.post(
    "/{project_id}/experiments/claim-run",
    response_model=ProjectOut,
    summary="Run and save a paper-grounded attention scaling stress test",
)
async def claim_stress_test(
    project_id: uuid.UUID,
    body: ClaimStressTestRequest,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
) -> ProjectOut:
    project = await get_project(db, user.id, project_id)
    paper_ids = set(await project_papers(db, settings, project))
    if not paper_ids:
        raise ConflictError("There are no papers in this project's scope yet.")

    rows = await db.execute(
        select(Chunk, Document)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Chunk.id.in_(body.evidence_chunk_ids),
            Chunk.user_id == user.id,
            Document.user_id == user.id,
            Document.id.in_(paper_ids),
        )
    )
    passages = {chunk.id: (chunk, document) for chunk, document in rows.all()}
    if set(passages) != set(body.evidence_chunk_ids):
        raise ValidationError(
            "One or more evidence passages are no longer available in this project's papers. Search again."
        )

    run = run_claim_stress_test(body.dimensions, body.seed)
    run.update(
        {
            "id": str(uuid.uuid4()),
            "created_at": datetime.now(UTC).isoformat(),
            "claim": body.claim.strip(),
            "question": project.question.strip() or project.idea,
            "hypothesis": project.hypothesis.strip(),
            "evidence": [
                {
                    "chunk_id": str(chunk.id),
                    "document_id": str(document.id),
                    "title": document.title,
                    "year": document.year,
                    "section_title": chunk.section_title,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "char_start": chunk.char_start,
                    "boxes": chunk.boxes,
                    "quote": chunk.text[:1800],
                }
                for chunk, document in (passages[chunk_id] for chunk_id in body.evidence_chunk_ids)
            ],
        }
    )
    steps = _steps(project)
    runs = list(steps["experiments"].get("claim_runs") or [])
    steps["experiments"]["claim_runs"] = [run, *runs][:10]
    project.steps = steps
    return await _out(db, project)


@router.post(
    "/{project_id}/experiments/analyze-results",
    response_model=ProjectOut,
    summary="Analyze and save a compact summary of the project's results.csv",
)
async def analyze_project_results(
    project_id: uuid.UUID,
    body: ResultsAnalysisRequest,
    user: CurrentUser,
    db: DbSession,
) -> ProjectOut:
    project = await get_project(db, user.id, project_id)
    try:
        analysis = analyze_results_csv(body.csv_text)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    analysis.update(
        {
            "id": str(uuid.uuid4()),
            "created_at": datetime.now(UTC).isoformat(),
            "filename": body.filename.replace("\\", "/").split("/")[-1],
        }
    )
    steps = _steps(project)
    saved = list(steps["experiments"].get("result_analyses") or [])
    steps["experiments"]["result_analyses"] = [analysis, *saved][:5]
    project.steps = steps
    return await _out(db, project)


@router.post(
    "/{project_id}/experiments/paper-run-matches",
    response_model=ProjectOut,
    summary="Compare an imported run summary with a cited result from a project paper",
)
async def create_paper_run_match(
    project_id: uuid.UUID,
    body: PaperRunMatchRequest,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
) -> ProjectOut:
    project = await get_project(db, user.id, project_id)
    steps = _steps(project)

    analysis_id = str(body.result_analysis_id)
    analysis = next(
        (item for item in steps["experiments"].get("result_analyses", []) if item.get("id") == analysis_id),
        None,
    )
    if analysis is None:
        raise ValidationError("That saved results analysis is no longer available. Import the results CSV again.")
    summary = next(
        (
            item for item in analysis.get("summaries", [])
            if item.get("experiment") == body.run_experiment
            and item.get("dataset") == body.run_dataset
            and item.get("system") == body.run_system
            and item.get("metric") == body.run_metric
        ),
        None,
    )
    if summary is None:
        raise ValidationError("The selected run summary was not found in that saved analysis. Refresh the results and try again.")

    paper_ids = await project_papers(db, settings, project)
    if not paper_ids:
        raise ConflictError("This project has no papers in scope. Add a paper before comparing its reported result.")
    rows = await db.execute(
        select(Chunk, Document)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Chunk.id == body.evidence_chunk_id,
            Chunk.user_id == user.id,
            Document.user_id == user.id,
            Document.id.in_(paper_ids),
        )
    )
    evidence = rows.first()
    if evidence is None:
        raise ValidationError("Choose a cited passage from a paper in this project's scope.")
    chunk, document = evidence

    try:
        assessed = assess_paper_run_match(
            paper_dataset=body.paper_dataset,
            paper_system=body.paper_system,
            paper_metric=body.paper_metric,
            paper_split=body.paper_split,
            run_dataset=body.run_dataset,
            run_system=body.run_system,
            run_metric=body.run_metric,
            run_split=body.run_split,
            reported_mean=body.reported_mean,
            reproduced_mean=float(summary["mean"]),
            tolerance=body.tolerance,
            map_labels=body.map_labels,
            mapping_note=body.mapping_note,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    match = {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(UTC).isoformat(),
        **assessed,
        "paper": {
            "document_id": str(document.id),
            "title": document.title,
            "year": document.year,
            "chunk_id": str(chunk.id),
            "section_title": chunk.section_title,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "char_start": chunk.char_start,
            "boxes": chunk.boxes,
            "quote": chunk.text[:1800],
            "kind": chunk.kind,
        },
        "reported": {
            "dataset": body.paper_dataset,
            "system": body.paper_system,
            "metric": body.paper_metric,
            "split": body.paper_split,
            "mean": body.reported_mean,
            "std": body.reported_std,
        },
        "run": {
            "analysis_id": analysis_id,
            "filename": analysis.get("filename", "results.csv"),
            "experiment": body.run_experiment,
            "dataset": body.run_dataset,
            "system": body.run_system,
            "metric": body.run_metric,
            "split": body.run_split,
            "mean": summary["mean"],
            "std": summary["std"],
            "seed_count": summary["seed_count"],
        },
    }
    saved = list(steps["experiments"].get("paper_run_matches") or [])
    steps["experiments"]["paper_run_matches"] = [match, *saved][:20]
    project.steps = steps
    return await _out(db, project)


@router.delete(
    "/{project_id}/experiments/paper-run-matches/{match_id}",
    response_model=ProjectOut,
    summary="Remove a saved paper-to-run comparison",
)
async def delete_paper_run_match(
    project_id: uuid.UUID,
    match_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
) -> ProjectOut:
    project = await get_project(db, user.id, project_id)
    steps = _steps(project)
    matches = list(steps["experiments"].get("paper_run_matches") or [])
    remaining = [item for item in matches if item.get("id") != str(match_id)]
    if len(remaining) == len(matches):
        raise NotFoundError("Paper-to-run comparison not found.")
    steps["experiments"]["paper_run_matches"] = remaining
    project.steps = steps
    return await _out(db, project)


@router.post(
    "/{project_id}/experiments/analyze-predictions",
    response_model=ProjectOut,
    summary="Analyze per-example predictions and save the hardest cases",
)
async def analyze_project_predictions(
    project_id: uuid.UUID,
    body: PredictionAnalysisRequest,
    user: CurrentUser,
    db: DbSession,
) -> ProjectOut:
    project = await get_project(db, user.id, project_id)
    try:
        analysis = analyze_predictions_jsonl(
            body.jsonl_text,
            body.metric,
            higher_is_better=body.higher_is_better,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    analysis.update(
        {
            "id": str(uuid.uuid4()),
            "created_at": datetime.now(UTC).isoformat(),
            "filename": body.filename.replace("\\", "/").split("/")[-1],
        }
    )
    steps = _steps(project)
    saved = list(steps["experiments"].get("prediction_analyses") or [])
    steps["experiments"]["prediction_analyses"] = [analysis, *saved][:3]
    project.steps = steps
    return await _out(db, project)


MEDIA = {
    "md": "text/markdown; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "latex": "application/zip",
    "code": "application/zip",
}


@router.get(
    "/{project_id}/guide/{step}",
    summary="A detailed, step-by-step guide to one step, adapted to this project",
)
async def guide(
    project_id: uuid.UUID,
    step: Literal["questions", "background", "gaps", "methods", "experiments", "outline", "code"],
    user: CurrentUser,
    db: DbSession,
) -> dict[str, Any]:
    project = await get_project(db, user.id, project_id)
    reports = await linked_reports(db, project)
    return step_guide(
        project, step, completion(project, reports), await scope_size(db, project, reports)
    )


@router.get(
    "/{project_id}/code",
    summary="Starter code generated from the plan: every file with what it is for",
)
async def starter_code(
    project_id: uuid.UUID, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> dict[str, Any]:
    project = await get_project(db, user.id, project_id)
    return {
        "files": codegen.starter_files(project, settings),
        "runs": _steps(project)["code"].get("runs", []),
    }


@router.put("/{project_id}/code-file", summary="Save an edited starter-code file to this project")
async def save_code_file(
    project_id: uuid.UUID,
    body: CodeFileEdit,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
) -> dict[str, str]:
    project = await get_project(db, user.id, project_id)
    files = codegen.starter_files(project, settings)
    if body.path not in {item["path"] for item in files}:
        raise ValidationError("That file isn't part of this project's starter code.")
    steps = _steps(project)
    saved = dict(steps["code"].get("files") or {})
    saved[body.path] = body.content
    steps["code"]["files"] = saved
    project.steps = steps
    await db.flush()
    return {"path": body.path, "status": "saved"}


@router.post("/{project_id}/code-file/check", summary="Check Python syntax without executing project code")
async def check_code_file(
    project_id: uuid.UUID,
    body: CodeFileEdit,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
) -> dict[str, Any]:
    project = await get_project(db, user.id, project_id)
    files = codegen.starter_files(project, settings)
    if body.path not in {item["path"] for item in files}:
        raise ValidationError("That file isn't part of this project's starter code.")
    if not body.path.endswith(".py"):
        raise ValidationError("Syntax checking is available for Python files.")
    try:
        ast.parse(body.content, filename=body.path)
    except SyntaxError as exc:
        return {
            "valid": False,
            "message": exc.msg,
            "line": exc.lineno,
            "column": exc.offset,
        }
    except (ValueError, RecursionError) as exc:
        return {"valid": False, "message": str(exc) or "Python couldn't parse this file."}
    return {
        "valid": True,
        "message": "Valid Python syntax. The code was checked but not executed.",
        "line": None,
        "column": None,
    }


@router.post(
    "/{project_id}/code/run",
    summary="Run the project's systems on the built-in toy dataset in an isolated container",
)
async def run_project_code(
    project_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
) -> dict[str, Any]:
    project = await get_project(db, user.id, project_id)
    files = {item["path"]: item["content"] for item in codegen.starter_files(project, settings)}
    total_bytes = sum(len(content.encode("utf-8")) for content in files.values())
    if total_bytes > 900_000:
        raise ValidationError(
            "The saved project files exceed the 900 KB runner limit. Reduce the file contents "
            "before running."
        )
    for path, content in files.items():
        if path.endswith(".py"):
            try:
                ast.parse(content, filename=path)
            except SyntaxError as exc:
                location = f" at line {exc.lineno}" if exc.lineno else ""
                raise ValidationError(f"{path}{location}: {exc.msg}") from exc
            except (ValueError, RecursionError) as exc:
                raise ValidationError(f"{path}: Python couldn't parse this file.") from exc

    result = await project_runner.run_toy_experiment(files, settings)
    manifest = hashlib.sha256(
        json.dumps(sorted(files.items()), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    run = {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(UTC).isoformat(),
        "mode": "toy",
        "status": "succeeded" if result["exit_code"] == 0 else "failed",
        "dataset": "Built-in toy dataset (four examples)",
        "split": "fixed toy examples",
        "seed": 0,
        "file_manifest_sha256": manifest,
        "runtime": {
            "python": result.get("python_version", "unknown"),
            "image_digest": result.get("image_digest", "unknown"),
            "packages": result.get("packages", []),
            "requirements_installed": False,
            "note": (
                "Only packages baked into the runner image are available; requirements.txt is not "
                "installed."
            ),
        },
        "duration_ms": result.get("duration_ms", 0),
        "timed_out": bool(result.get("timed_out", False)),
        "exit_code": result["exit_code"],
        "summary": result.get("summary", ""),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "results_csv": result.get("results_csv", ""),
        "results_csv_truncated": bool(result.get("results_csv_truncated", False)),
        "predictions_jsonl": result.get("predictions_jsonl", ""),
        "predictions_jsonl_truncated": bool(
            result.get("predictions_jsonl_truncated", False)
        ),
    }
    steps = _steps(project)
    steps["code"]["runs"] = [run, *steps["code"].get("runs", [])][:5]
    project.steps = steps
    await db.flush()
    return run


@router.get("/{project_id}/export", summary="The plan as Markdown or Word; the outline as LaTeX")
async def export_project(
    project_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
    format: Literal["md", "docx", "latex", "code"] = "md",
) -> Response:
    project = await get_project(db, user.id, project_id)
    reports = await linked_reports(db, project)
    if format == "latex":
        content, extension = await export.outline_latex(db, project), "zip"
    elif format == "code":
        content, extension = codegen.starter_zip(project, settings), "zip"
    else:
        markdown = export.plan_markdown(project, reports)
        content = markdown.encode() if format == "md" else export.plan_docx(markdown)
        extension = format
    slug = (
        "".join(c if c.isalnum() else "-" for c in project.title.lower()).strip("-")[:60]
        or "project"
    )
    slug = "-".join(part for part in slug.split("-") if part)
    if format == "code":
        slug += "-starter-code"
    return Response(
        content,
        media_type=MEDIA[format],
        headers={"Content-Disposition": f'attachment; filename="{slug}.{extension}"'},
    )
