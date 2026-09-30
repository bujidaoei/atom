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
from ..models import AcceptanceRun, Message, Project, Race, RaceHeat, Requirement
from ..serialize import acceptance_json, project_detail, project_summary, race_json
from ..services.orchestrator import orchestrator
from ..services.parsing import fallback_title

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
    body: CreateProject, user: CurrentUser, session: DbSession
) -> dict[str, object]:
    prompt = body.prompt.strip()
    project = Project(user_id=user.id, prompt=prompt, title=fallback_title(prompt))
    session.add(project)
    session.flush()
    session.add(Message(project_id=project.id, role="user", content=prompt))
    session.commit()
    storage.ensure_project_dirs(project.id)
    return {"project": project_detail(session, project)}


@router.get("/{project_id}")
def read_project(project: OwnedProject, session: DbSession) -> dict[str, object]:
    return {"project": project_detail(session, project)}


@router.delete("/{project_id}")
async def delete_project(project: OwnedProject, session: DbSession) -> dict[str, bool]:
    await orchestrator.cancel(project.id)
    project_id = project.id
    session.delete(project)
    session.commit()
    storage.remove_project_dirs(project_id)
    return {"ok": True}


@router.get("/{project_id}/files/{path:path}", response_class=PlainTextResponse)
def read_file(project: OwnedProject, path: str) -> PlainTextResponse:
    target = storage.resolve_within(storage.workspace_dir(project.id), path)
    if target is None or not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文件不存在")
    if target.suffix.lower() not in _TEXT_SUFFIXES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "该文件不是文本")
    try:
        return PlainTextResponse(target.read_text("utf-8"))
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
async def plan(project: OwnedProject, user: CurrentUser) -> dict[str, str]:
    _guard(project, {"draft", "error", "cancelled", "timed_out", "interrupted"})
    try:
        job = await orchestrator.start_plan(project.id, user.id)
    except AtomError as error:
        raise HTTPException(error.status_code, error.detail) from error
    return {"runId": job}


@router.post("/{project_id}/approve")
async def approve(
    body: ApproveBody, project: OwnedProject, user: CurrentUser
) -> dict[str, str]:
    _guard(project, {"awaiting_approval"})
    try:
        job = await orchestrator.start_build(project.id, user.id, body.note)
    except AtomError as error:
        raise HTTPException(error.status_code, error.detail) from error
    return {"runId": job}


@router.post("/{project_id}/revise")
async def revise(
    body: ReviseBody, project: OwnedProject, user: CurrentUser
) -> dict[str, str]:
    _guard(project, {"ready", "error", "cancelled", "timed_out", "interrupted"})
    try:
        job = await orchestrator.start_revise(project.id, user.id, body.message.strip())
    except AtomError as error:
        raise HTTPException(error.status_code, error.detail) from error
    return {"runId": job}


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
    body: RaceBody, project: OwnedProject, user: CurrentUser, session: DbSession
) -> dict[str, object]:
    _guard(project, {"awaiting_approval", "ready", "error"})
    models = list(dict.fromkeys(m.strip() for m in body.models if m.strip()))
    if len(models) < 2:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "至少选择两个不同的模型")
    if len(models) > get_settings().race_max_models:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "最多同时比拼 4 个模型")
    if user.credits < len(models):
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "额度不足以发起这场比拼")

    try:
        race_id = orchestrator.create_race(project.id, models)
        await orchestrator.start_race(project.id, user.id, race_id)
    except AtomError as error:
        raise HTTPException(error.status_code, error.detail) from error

    session.expire_all()
    race = race_json(session, project.id)
    return {"raceId": race_id, "heats": race["heats"] if race else []}


@router.get("/{project_id}/race")
def read_race(project: OwnedProject, session: DbSession) -> dict[str, object]:
    session.expire_all()
    return {"race": race_json(session, project.id)}


@router.post("/{project_id}/race/{heat_id}/adopt")
def adopt_heat(
    project: OwnedProject, heat_id: str, session: DbSession
) -> dict[str, bool]:
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
