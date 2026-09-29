import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user, owned_project
from app.errors import ContractError, GatewayError
from app.models import AcceptanceRun, Project, Usage, User, utcnow
from app.schemas import AcceptanceIn, PreviewStateIn, ProjectIn, ReviseIn
from app.serialize import project_detail, project_summary
from app.services.acceptance import evaluate_static, merge_acceptance
from app.services.pipeline import (
    apply_amendment,
    build_project,
    plan_project,
    read_html,
    requirement_payload,
    revise_project,
)

router = APIRouter(tags=["projects"])


def _fail(db: Session, project: Project, exc: Exception, status: int) -> None:
    db.rollback()
    fresh = db.get(Project, project.id)
    if fresh is None:
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    fresh.status = "error"
    fresh.error_message = str(exc)[:500]
    fresh.updated_at = utcnow()
    db.commit()
    raise HTTPException(status_code=status, detail=str(exc)) from exc


async def _run(db: Session, project: Project, action):
    try:
        return await action()
    except GatewayError as exc:
        _fail(db, project, exc, 502)
    except ContractError as exc:
        _fail(db, project, exc, 422)
    except json.JSONDecodeError as exc:
        _fail(db, project, ContractError("模型返回的结构无法读取"), 422)


@router.get("/projects")
def list_projects(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(
        select(Project).where(Project.user_id == user.id).order_by(Project.updated_at.desc())
    ).all()
    return [project_summary(row) for row in rows]


@router.post("/projects")
def create_project(
    body: ProjectIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = Project(user_id=user.id, prompt=body.prompt.strip(), name="未命名", status="draft")
    db.add(project)
    db.commit()
    db.refresh(project)
    return project_detail(db, project)


@router.get("/projects/{project_id}")
def get_project(
    project_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return project_detail(db, owned_project(db, user, project_id))


@router.delete("/projects/{project_id}")
def delete_project(
    project_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = owned_project(db, user, project_id)
    db.delete(project)
    db.commit()
    return {"ok": True}


@router.post("/projects/{project_id}/plan")
async def plan(
    project_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = owned_project(db, user, project_id)
    if project.contract_locked:
        raise HTTPException(status_code=409, detail="契约已锁定。要改范围，请在对话里提出修订。")
    await _run(db, project, lambda: plan_project(db, project, user))
    db.refresh(project)
    return project_detail(db, project)


@router.post("/projects/{project_id}/build")
async def build(
    project_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = owned_project(db, user, project_id)
    if not project.requirements:
        raise HTTPException(status_code=409, detail="还没有契约，不能构建。")
    await _run(db, project, lambda: build_project(db, project, user))
    db.refresh(project)
    return project_detail(db, project)


@router.post("/projects/{project_id}/revise")
async def revise(
    project_id: str,
    body: ReviseIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = owned_project(db, user, project_id)
    await _run(db, project, lambda: revise_project(db, project, user, body.instruction))
    db.refresh(project)
    return project_detail(db, project)


@router.post("/projects/{project_id}/amendments/apply")
async def apply(
    project_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = owned_project(db, user, project_id)
    await _run(db, project, lambda: apply_amendment(db, project, user))
    db.refresh(project)
    return project_detail(db, project)


@router.post("/projects/{project_id}/amendments/discard")
def discard(
    project_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = owned_project(db, user, project_id)
    project.pending_amendment = ""
    project.updated_at = utcnow()
    db.commit()
    db.refresh(project)
    return project_detail(db, project)


@router.put("/projects/{project_id}/preview-state")
def save_preview_state(
    project_id: str,
    body: PreviewStateIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = owned_project(db, user, project_id)
    snapshot = {}
    for key, value in list(body.snapshot.items())[:40]:
        if not isinstance(key, str) or len(key) > 80:
            continue
        snapshot[key] = str(value)[:20000]
    project.preview_state = json.dumps(snapshot, ensure_ascii=False)
    project.updated_at = utcnow()
    db.commit()
    return {"ok": True}


@router.post("/projects/{project_id}/acceptance")
def accept(
    project_id: str,
    body: AcceptanceIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = owned_project(db, user, project_id)
    html = read_html(db, project)
    if not html:
        raise HTTPException(status_code=409, detail="还没有页面可以验收。")
    requirements = requirement_payload(db, project)
    merged = merge_acceptance(
        evaluate_static(html, requirements),
        [item.model_dump() for item in body.runtime],
        requirements,
    )
    run = AcceptanceRun(
        project_id=project.id,
        passed=merged["passed"],
        total=merged["total"],
        results_json=json.dumps(merged, ensure_ascii=False),
    )
    db.add(run)
    project.updated_at = utcnow()
    db.commit()
    db.refresh(project)
    return project_detail(db, project)


@router.get("/usage")
def usage(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    row = db.execute(
        select(
            func.count(Usage.id),
            func.coalesce(func.sum(Usage.prompt_tokens), 0),
            func.coalesce(func.sum(Usage.completion_tokens), 0),
        ).where(Usage.user_id == user.id)
    ).one()
    return {
        "calls": int(row[0] or 0),
        "prompt_tokens": int(row[1] or 0),
        "completion_tokens": int(row[2] or 0),
    }
