import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AcceptanceRun, Message, Project
from app.services.acceptance import loads_json
from app.services.pipeline import read_html, requirement_payload


def iso(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def acceptance_out(run: AcceptanceRun | None) -> dict | None:
    if run is None:
        return None
    payload = loads_json(run.results_json, {})
    return {
        "id": run.id,
        "passed": run.passed,
        "total": run.total,
        "created_at": iso(run.created_at),
        "items": payload.get("items", []),
    }


def project_summary(project: Project) -> dict:
    return {
        "id": project.id,
        "name": project.name,
        "prompt": project.prompt,
        "status": project.status,
        "contract_locked": project.contract_locked,
        "contract_version": project.contract_version,
        "updated_at": iso(project.updated_at),
    }


def project_detail(db: Session, project: Project) -> dict:
    requirements = requirement_payload(db, project)
    html = read_html(db, project)
    messages = db.scalars(
        select(Message).where(Message.project_id == project.id).order_by(Message.created_at)
    ).all()
    runs = db.scalars(
        select(AcceptanceRun).where(AcceptanceRun.project_id == project.id).order_by(AcceptanceRun.created_at)
    ).all()
    pending = loads_json(project.pending_amendment, None)
    return {
        **project_summary(project),
        "error_message": project.error_message,
        "lead_note": project.lead_note,
        "research_note": project.research_note,
        "architecture_note": project.architecture_note,
        "requirements": requirements,
        "messages": [
            {
                "id": item.id,
                "role": item.role,
                "content": item.content,
                "created_at": iso(item.created_at),
            }
            for item in messages
        ],
        "html": html,
        "files": [
            {"path": "index.html", "content": html},
            {
                "path": "contract.json",
                "content": json.dumps(requirements, ensure_ascii=False, indent=2),
            },
        ],
        "trace": loads_json(project.trace_json, []),
        "preview_state": loads_json(project.preview_state, {}),
        "pending_amendment": pending if isinstance(pending, dict) else None,
        "latest_acceptance": acceptance_out(runs[-1] if runs else None),
    }
