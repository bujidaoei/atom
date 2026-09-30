from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import storage
from .config import get_settings
from .models import AcceptanceRun, Project, Race, Run, User


def user_json(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "credits": user.credits,
    }


def project_summary(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "title": project.title,
        "summary": project.summary,
        "kind": project.kind,
        "status": project.status,
        "slug": project.slug,
        "publishedAt": project.published_at.isoformat()
        if project.published_at
        else None,
        "createdAt": project.created_at.isoformat(),
        "updatedAt": project.updated_at.isoformat(),
    }


def project_detail(session: Session, project: Project) -> dict[str, Any]:
    detail = project_summary(project)
    latest = session.scalar(
        select(Run)
        .where(Run.project_id == project.id)
        .order_by(Run.started_at.desc())
        .limit(1)
    )
    detail.update(
        {
            "prompt": project.prompt,
            "activeRunId": project.active_run_id,
            "latestRun": (
                {
                    "id": latest.id,
                    "status": latest.status,
                    "phase": latest.phase,
                    "error": latest.error,
                    "startedAt": latest.started_at.isoformat(),
                    "finishedAt": latest.finished_at.isoformat()
                    if latest.finished_at
                    else None,
                }
                if latest
                else None
            ),
            "buildBudgetSeconds": get_settings().build_budget_seconds,
            "messages": [
                {
                    "id": message.id,
                    "role": message.role,
                    "content": message.content,
                    "runId": message.run_id,
                    "createdAt": message.created_at.isoformat(),
                }
                for message in project.messages
            ],
            "requirements": [
                {
                    "key": requirement.key,
                    "title": requirement.title,
                    "detail": requirement.detail,
                    "checks": json.loads(requirement.checks_json),
                }
                for requirement in project.requirements
            ],
            "files": storage.list_files(storage.workspace_dir(project.id)),
            "acceptance": acceptance_json(session, project.id),
            "race": race_json(session, project.id),
        }
    )
    return detail


def acceptance_json(session: Session, project_id: str) -> dict[str, Any] | None:
    run = session.scalars(
        select(AcceptanceRun)
        .where(AcceptanceRun.project_id == project_id)
        .order_by(AcceptanceRun.created_at.desc())
        .limit(1)
    ).first()
    if run is None:
        return None
    last_change = session.scalar(
        select(Run.started_at)
        .where(Run.project_id == project_id, Run.phase.in_(("build", "revise", "race")))
        .order_by(Run.started_at.desc())
        .limit(1)
    )
    if last_change and run.created_at < last_change:
        return None  # Preserve historical evidence; never present it for new code.
    return {
        "id": run.id,
        "passed": run.passed,
        "total": run.total,
        "results": json.loads(run.results_json),
        "createdAt": run.created_at.isoformat(),
    }


def race_json(session: Session, project_id: str) -> dict[str, Any] | None:
    race = session.scalars(
        select(Race)
        .where(Race.project_id == project_id)
        .order_by(Race.created_at.desc())
        .limit(1)
    ).first()
    if race is None:
        return None
    return {
        "id": race.id,
        "status": race.status,
        "winnerHeatId": race.winner_heat_id,
        "createdAt": race.created_at.isoformat(),
        "heats": [
            {
                "id": heat.id,
                "model": heat.model,
                "status": heat.status,
                "runId": heat.run_id,
                "previewUrl": (
                    f"/preview/{project_id}/race/{heat.id}/"
                    if heat.status in {"done", "running"}
                    else None
                ),
                "elapsedMs": heat.elapsed_ms,
                "inputTokens": heat.input_tokens,
                "outputTokens": heat.output_tokens,
                "fileCount": heat.file_count,
                "bytes": heat.bytes,
                "error": heat.error,
            }
            for heat in race.heats
        ],
    }
