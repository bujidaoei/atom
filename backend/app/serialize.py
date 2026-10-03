from __future__ import annotations

import json
from datetime import datetime, timezone
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
        "canRevokeSessions": get_settings().session_mode == "durable",
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


def project_detail(session: Session, project: Project, *, catalog=None) -> dict[str, Any]:
    if get_settings().sandbox_mode == "broker" and catalog is None:
        raise RuntimeError("committed_catalog_required")
    listing = catalog() if catalog else None
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
            "legacyPublicationAvailable": get_settings().sandbox_mode != "broker",
            "revisionAdoptionAvailable": get_settings().sandbox_mode == "broker"
            and get_settings().session_mode == "durable",
            "isolatedPreviewEnabled": get_settings().ip_preview_enabled,
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
            "files": listing["files"] if listing is not None else storage.list_files(storage.workspace_dir(project.id)),
            "revisionId": listing["revisionId"] if listing is not None else None,
            "incompleteSavedRevisionId": listing["incompleteSavedRevisionId"] if listing is not None else None,
            "acceptance": acceptance_json(session, project.id),
            "race": race_json(session, project.id, catalog=catalog),
        }
    )
    return detail


def _utc(value: datetime) -> datetime:
    """Persisted model times are UTC; SQLite returns them without tzinfo.

    Newly committed objects retain their timezone in the identity map. Apply
    the same time semantics before comparison and JSON serialization in both
    cases, without interpreting naive stored values as the server's local time.
    """
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


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
    created_at = _utc(run.created_at)
    if last_change and created_at < _utc(last_change):
        return None  # Preserve historical evidence; never present it for new code.
    return {
        "id": run.id,
        "passed": run.passed,
        "total": run.total,
        "results": json.loads(run.results_json),
        "createdAt": created_at.isoformat(),
    }


def race_json(session: Session, project_id: str, *, catalog=None) -> dict[str, Any] | None:
    if get_settings().sandbox_mode == "broker" and catalog is None:
        raise RuntimeError("committed_catalog_required")
    race = session.scalars(
        select(Race)
        .where(Race.project_id == project_id)
        .order_by(Race.created_at.desc())
        .limit(1)
    ).first()
    if race is None:
        return None
    listings = {heat.id: catalog(heat.id) for heat in race.heats} if catalog else {}
    previewable = {
        heat.id: any(item["path"] == "index.html" for item in listings[heat.id]["files"])
        if catalog else heat.status in {"done", "running"}
        or (storage.workspace_dir(project_id, heat.id) / "index.html").is_file()
        for heat in race.heats
    }
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
                "runStartedAt": (
                    run.started_at.replace(tzinfo=timezone.utc).isoformat()
                    if (run := session.get(Run, heat.run_id))
                    else None
                )
                if heat.run_id
                else None,
                "revisionId": listings[heat.id]["revisionId"] if catalog else None,
                "incompleteSavedRevisionId": listings[heat.id]["incompleteSavedRevisionId"] if catalog else None,
                "previewUrl": f"/preview/{project_id}/race/{heat.id}/" if previewable[heat.id] else None,
                "elapsedMs": heat.elapsed_ms,
                "inputTokens": heat.input_tokens,
                "outputTokens": heat.output_tokens,
                "fileCount": len(listings[heat.id]["files"]) if catalog else heat.file_count,
                "bytes": sum(item["bytes"] for item in listings[heat.id]["files"]) if catalog else heat.bytes,
                "error": heat.error,
            }
            for heat in race.heats
        ],
    }
