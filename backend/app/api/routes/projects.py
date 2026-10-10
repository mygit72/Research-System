"""Research Project Builder: a guided plan from an idea to a paper outline."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, DbSession, JobServiceDep, SettingsDep
from app.models.project import ResearchProject
from app.schemas.project import (
    ExperimentPlanRequest,
    ProjectCreate,
    ProjectGuidance,
    ProjectOut,
    ProjectSummary,
    ProjectUpdate,
)
from app.schemas.report import ReportSummary
from app.schemas.summary import SummaryProgress
from app.services.projects import codegen, export
from app.services.projects.guide import step_guide
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
    request_suggestions,
    scope_size,
    start_report,
    suggest_methods,
)

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
    summary="Suggest research questions, or draft the paper outline (background job)",
)
async def suggest(
    project_id: uuid.UUID,
    step: Literal["questions", "outline"],
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
    return {"files": codegen.starter_files(project, settings)}


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
