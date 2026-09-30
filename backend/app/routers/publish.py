from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from .. import storage
from ..deps import DbSession, OwnedProject
from ..models import Publication

router = APIRouter(prefix="/projects", tags=["publish"])

_SLUG_SAFE = re.compile(r"[^a-z0-9]+")


def _slugify(title: str) -> str:
    base = _SLUG_SAFE.sub("-", title.strip().lower()).strip("-")
    # Chinese titles reduce to nothing, so fall back to a neutral stem.
    return (base[:40] or "atoms-app") + "-" + secrets.token_hex(2)


@router.post("/{project_id}/publish")
def publish(project: OwnedProject, session: DbSession) -> dict[str, str]:
    if project.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "生成尚未完成，请完成后再发布")
    workspace = storage.workspace_dir(project.id)
    if not (workspace / "index.html").is_file():
        raise HTTPException(status.HTTP_409_CONFLICT, "还没有可发布的页面")

    slug = project.slug or _slugify(project.title)
    storage.copy_tree(workspace, storage.published_dir(slug))

    if session.get(Publication, slug) is None:
        session.add(Publication(slug=slug, project_id=project.id, live=True))
    else:
        session.get(Publication, slug).live = True

    project.slug = slug
    project.published_at = datetime.now(timezone.utc)
    session.commit()
    return {"slug": slug, "url": f"/p/{slug}"}


@router.post("/{project_id}/unpublish")
def unpublish(project: OwnedProject, session: DbSession) -> dict[str, bool]:
    if project.slug:
        publication = session.get(Publication, project.slug)
        if publication:
            publication.live = False
    project.slug = None
    project.published_at = None
    session.commit()
    return {"ok": True}
