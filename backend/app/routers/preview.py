from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import FileResponse

from .. import storage
from ..config import get_settings
from ..revision_http import project_revision_view
from ..deps import DbSession, OptionalUser
from ..models import Project, Publication

router = APIRouter(tags=["preview"])

_INDEX = "index.html"


def _serve(root: Path, relative: str, *, revision_id: str | None = None) -> Response:
    """Serve a workspace as a static site.

    Directory requests fall back to index.html so client-side routing in a
    generated app behaves the way it would on a real host.
    """
    relative = relative.strip("/")
    target = storage.resolve_within(root, relative) if relative else root / _INDEX
    if target is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "路径不合法")
    if target.is_dir():
        target = target / _INDEX
    if not target.is_file():
        fallback = root / _INDEX
        if not fallback.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "还没有可预览的内容")
        target = fallback

    media_type, _ = mimetypes.guess_type(target.name)
    # Existing acceptance uses same-origin framing; origin isolation remains a
    # separate deployment boundary from committed artifact selection.
    headers = {
        "X-Frame-Options": "SAMEORIGIN",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if revision_id is not None:
        headers['X-Atom-Revision'] = revision_id
        # Consume within the private view lifetime; never stream a deleted path.
        return Response(target.read_bytes(), media_type=media_type or 'application/octet-stream', headers=headers)
    return FileResponse(
        target,
        media_type=media_type or "application/octet-stream",
        headers=headers,
    )


@router.get("/preview/{project_id}/{path:path}")
def preview(
    project_id: str, path: str, session: DbSession, user: OptionalUser, request: Request
) -> Response:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在")
    owns = user is not None and project.user_id == user.id
    committed = get_settings().sandbox_mode == 'broker'
    if committed and not owns:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在")
    if not owns and project.slug is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在")

    # Race heats live under race/<heatId>/ inside the project directory.
    parts = path.strip("/").split("/", 2)
    if committed:
        heat = parts[1] if len(parts) >= 2 and parts[0] == 'race' else None
        relative = (parts[2] if len(parts) > 2 else '') if heat is not None else path
        with project_revision_view(request, project, heat) as view:
            return _serve(view.path, relative, revision_id=view.revision.revision_id)
    if len(parts) >= 2 and parts[0] == "race":
        root = storage.workspace_dir(project_id, parts[1])
        return _serve(root, parts[2] if len(parts) > 2 else "")
    return _serve(storage.workspace_dir(project_id), path)


@router.get("/p/{slug}/{path:path}")
def published(slug: str, path: str, session: DbSession) -> Response:
    publication = session.get(Publication, slug)
    if publication is None or not publication.live:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该页面不存在或已下线")
    return _serve(storage.published_dir(slug), path)


@router.get("/p/{slug}")
def published_root(slug: str, session: DbSession) -> Response:
    return published(slug, "", session)
