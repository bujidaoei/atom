from __future__ import annotations

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import storage
from ..config import get_settings
from ..deps import CurrentUser, DbSession, OwnedProject
from ..errors import AtomError
from ..events import bus
from ..revision_http import project_revision_view, project_catalog
from ..models import AcceptanceRun, Message, Project, Race, RaceHeat, Requirement
from ..serialize import acceptance_json, project_detail, project_summary, race_json
from ..services.orchestrator import orchestrator
from ..services.parsing import fallback_title
from ..services.commands import Command

router = APIRouter(prefix="/projects", tags=["projects"])

HEARTBEAT_SECONDS = 15
# Anything the agent writes that a browser should never be handed back.
_TEXT_SUFFIXES = {
    ".html",
    ".htm",
    ".css",
    ".js",
    ".mjs",
    ".json",
    ".md",
    ".txt",
    ".svg",
    ".ts",
    ".jsx",
    ".tsx",
    ".yml",
    ".yaml",
    ".csv",
}


class CreateProject(BaseModel):
    prompt: str = Field(min_length=2, max_length=4000)


class ApproveBody(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class ReviseBody(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class AcceptanceResult(BaseModel):
    key: str
    checkIndex: int
    passed: bool
    note: str = ""


class AcceptanceBody(BaseModel):
    results: list[AcceptanceResult]


class RaceBody(BaseModel):
    models: list[str] = Field(min_length=2, max_length=4)
    budgetSeconds: int = Field(default=180, ge=180, le=600)


class RetryHeatBody(BaseModel):
    budgetSeconds: int = Field(default=360, ge=180, le=600)


@router.get("")
def list_projects(user: CurrentUser, session: DbSession) -> dict[str, object]:
    projects = session.scalars(
        select(Project)
        .where(Project.user_id == user.id)
        .order_by(Project.updated_at.desc())
    ).all()
    return {"projects": [project_summary(project) for project in projects]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_project(
    body: CreateProject, user: CurrentUser, session: DbSession, request: Request
) -> dict[str, object]:
    prompt = body.prompt.strip()
    project = Project(user_id=user.id, prompt=prompt, title=fallback_title(prompt))
    session.add(project)
    session.flush()
    session.add(Message(project_id=project.id, role="user", content=prompt))
    session.commit()
    storage.ensure_project_dirs(project.id)
    return {"project": project_detail(session, project, catalog=project_catalog(request, project) if get_settings().sandbox_mode == "broker" else None)}


@router.get("/{project_id}")
def read_project(project: OwnedProject, session: DbSession, request: Request) -> dict[str, object]:
    return {"project": project_detail(session, project, catalog=project_catalog(request, project) if get_settings().sandbox_mode == "broker" else None)}


@router.delete("/{project_id}")
async def delete_project(project: OwnedProject, session: DbSession) -> dict[str, bool]:
    await orchestrator.cancel(project.id)
    project_id = project.id
    session.delete(project)
    session.commit()
    storage.remove_project_dirs(project_id)
    return {"ok": True}


@router.get("/{project_id}/files/{path:path}", response_class=PlainTextResponse)
def read_file(project: OwnedProject, path: str, request: Request) -> PlainTextResponse:
    if get_settings().sandbox_mode == 'broker':
        with project_revision_view(request, project) as view:
            return _read_text(view.path, path, revision_id=view.revision.revision_id)
    return _read_text(storage.workspace_dir(project.id), path)


def _read_text(root, path: str, *, revision_id: str | None = None) -> PlainTextResponse:
    target = storage.resolve_within(root, path)
    if target is None or not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文件不存在")
    if target.suffix.lower() not in _TEXT_SUFFIXES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "该文件不是文本")
    try:
        return PlainTextResponse(target.read_text("utf-8"), headers={
            'X-Atom-Revision':revision_id, 'Cache-Control':'no-store'
        } if revision_id is not None else None)
    except (UnicodeDecodeError, OSError):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "该文件不是文本"
        ) from None


# ------------------------------------------------------------------ actions


def _guard(project: Project, allowed: set[str]) -> None:
    if orchestrator.active(project.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "该项目已有任务在运行")
    if project.status not in allowed:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"当前状态 {project.status} 不允许这个操作"
        )


@router.post("/{project_id}/plan")
async def plan(
    project: OwnedProject, user: CurrentUser, session: DbSession, request: Request
) -> dict[str, str]:
    command = Command(session, project.id, request, "plan")
    if (replay := command.replay()) is not None:
        return replay
    _guard(project, {"draft", "error", "cancelled", "timed_out", "interrupted"})
    try:
        job = await orchestrator.start_plan(project.id, user.id)
    except AtomError as error:
        raise HTTPException(error.status_code, error.detail) from error
    return command.save({"runId": job})


@router.post("/{project_id}/approve")
async def approve(
    body: ApproveBody,
    project: OwnedProject,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> dict[str, str]:
    command = Command(session, project.id, request, "approve", body.model_dump())
    if (replay := command.replay()) is not None:
        return replay
    _guard(project, {"awaiting_approval"})
    try:
        job = await orchestrator.start_build(project.id, user.id, body.note)
    except AtomError as error:
        raise HTTPException(error.status_code, error.detail) from error
    return command.save({"runId": job})


@router.post("/{project_id}/revise")
async def revise(
    body: ReviseBody,
    project: OwnedProject,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> dict[str, str]:
    command = Command(session, project.id, request, "revise", body.model_dump())
    if (replay := command.replay()) is not None:
        return replay
    _guard(project, {"ready", "error", "cancelled", "timed_out", "interrupted"})
    try:
        job = await orchestrator.start_revise(project.id, user.id, body.message.strip())
    except AtomError as error:
        raise HTTPException(error.status_code, error.detail) from error
    return command.save({"runId": job})


@router.post("/{project_id}/cancel")
async def cancel(project: OwnedProject) -> dict[str, bool]:
    await orchestrator.cancel(project.id)
    return {"ok": True}


# ------------------------------------------------------------------- stream


@router.get("/{project_id}/events")
async def events(
    project: OwnedProject,
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    """Server-sent events for one project.

    Replays everything after ``after`` before switching to live delivery, so a
    reconnecting browser never misses a token. Subscription happens before the
    replay read to close the gap where an event could land in between.
    """
    project_id = project.id
    queue = await bus.subscribe(project_id)

    async def stream():
        try:
            highest = after
            for event in bus.replay(project_id, after):
                highest = max(highest, event.seq)
                yield f"event: run\ndata: {event.to_json()}\n\n"

            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=HEARTBEAT_SECONDS
                    )
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if event.type == "stream.resync":
                    return
                if event.seq <= highest:
                    continue  # already delivered by the replay
                highest = event.seq
                yield f"event: run\ndata: {event.to_json()}\n\n"
        finally:
            await bus.unsubscribe(project_id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --------------------------------------------------------------- acceptance


@router.post("/{project_id}/acceptance")
def record_acceptance(
    body: AcceptanceBody, project: OwnedProject, session: DbSession
) -> dict[str, object]:
    """Store results the browser produced by running Emma's checks for real.

    Reported keys are intersected with the stored contract so a client cannot
    invent passing checks that were never specified.
    """
    valid: dict[str, int] = {}
    for requirement in session.scalars(
        select(Requirement).where(Requirement.project_id == project.id)
    ):
        valid[requirement.key] = len(json.loads(requirement.checks_json))

    expected = {(key, index) for key, count in valid.items() for index in range(count)}
    actual = [(result.key, result.checkIndex) for result in body.results]
    if not expected or set(actual) != expected or len(actual) != len(expected):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "验收结果必须完整覆盖契约，不能重复或包含未知检查",
        )
    if orchestrator.active(project.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "请等待生成结束后运行验收")
    results = [result.model_dump() for result in body.results]
    total = sum(valid.values())
    passed = sum(1 for result in results if result["passed"])

    run = AcceptanceRun(
        project_id=project.id,
        passed=passed,
        total=total,
        results_json=json.dumps(results, ensure_ascii=False),
    )
    session.add(run)
    session.commit()
    return {"acceptance": acceptance_json(session, project.id)}


# --------------------------------------------------------------- race mode


@router.post("/{project_id}/race")
async def start_race(
    body: RaceBody,
    project: OwnedProject,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> dict[str, object]:
    command = Command(session, project.id, request, "race", body.model_dump())
    if (replay := command.replay()) is not None:
        return replay
    _guard(
        project,
        {
            "awaiting_approval",
            "ready",
            "error",
            "timed_out",
            "cancelled",
            "interrupted",
        },
    )
    models = list(dict.fromkeys(m.strip() for m in body.models if m.strip()))
    if len(models) < 2:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "至少选择两个不同的模型")
    if len(models) > get_settings().race_max_models:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "最多同时比拼 4 个模型")
    if user.credits < len(models):
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "额度不足以发起这场比拼")

    try:
        race_id = orchestrator.create_race(project.id, models)
        await orchestrator.start_race(project.id, user.id, race_id, body.budgetSeconds)
    except AtomError as error:
        raise HTTPException(error.status_code, error.detail) from error

    session.expire_all()
    race = await asyncio.to_thread(
        race_json, session, project.id,
        catalog=project_catalog(request, project) if get_settings().sandbox_mode == "broker" else None,
    )
    return command.save({"raceId": race_id, "heats": race["heats"] if race else []})


@router.post("/{project_id}/race/{heat_id}/retry")
async def retry_heat(
    body: RetryHeatBody,
    project: OwnedProject,
    heat_id: str,
    user: CurrentUser,
    session: DbSession,
    request: Request,
):
    command = Command(
        session, project.id, request, f"retry:{heat_id}", body.model_dump()
    )
    if (replay := command.replay()) is not None:
        return replay
    _guard(
        project,
        {
            "awaiting_approval",
            "ready",
            "error",
            "timed_out",
            "cancelled",
            "interrupted",
        },
    )
    heat = session.get(RaceHeat, heat_id)
    race = session.get(Race, heat.race_id) if heat else None
    latest = session.scalar(
        select(Race.id)
        .where(Race.project_id == project.id)
        .order_by(Race.created_at.desc())
        .limit(1)
    )
    if race is None or race.project_id != project.id or race.id != latest:
        raise HTTPException(404, "该赛道不属于当前竞速")
    if heat.status not in {"failed", "error", "timed_out", "cancelled", "interrupted"}:
        raise HTTPException(409, "只能继续未完成的赛道")
    if user.credits < 1:
        raise HTTPException(402, "额度不足以继续赛道")
    race.status = "running"
    heat.status, heat.error = "queued", None
    session.commit()
    job = await orchestrator.start_race(
        project.id, user.id, race.id, body.budgetSeconds, heat_id
    )
    return command.save({"runId": job})


@router.get("/{project_id}/race")
def read_race(project: OwnedProject, session: DbSession, request: Request) -> dict[str, object]:
    session.expire_all()
    return {"race": race_json(session, project.id, catalog=project_catalog(request, project) if get_settings().sandbox_mode == "broker" else None)}


@router.post("/{project_id}/race/{heat_id}/adopt")
def adopt_heat(
    project: OwnedProject, heat_id: str, session: DbSession
) -> dict[str, bool]:
    if get_settings().sandbox_mode == "broker":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "隔离赛道尚无按修订确认的采用入口，不能通过旧目录复制采用",
        )
    if orchestrator.active(project.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "请等待所有赛道结束后再采用")
    heat = session.get(RaceHeat, heat_id)
    race = session.get(Race, heat.race_id) if heat else None
    if heat is None or race is None or race.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该赛道不存在")
    if heat.status != "done":
        raise HTTPException(status.HTTP_409_CONFLICT, "该赛道还没有完成")

    source = storage.workspace_dir(project.id, heat_id)
    if not source.is_dir():
        raise HTTPException(status.HTTP_409_CONFLICT, "该赛道没有产出文件")

    storage.copy_tree(source, storage.workspace_dir(project.id))
    race.winner_heat_id = heat_id
    project.status = "ready"
    session.commit()
    return {"ok": True}
