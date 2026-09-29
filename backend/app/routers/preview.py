from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import FileResponse

from .. import storage
from ..deps import DbSession, OptionalUser
from ..models import Project, Publication

router = APIRouter(tags=["preview"])

_INDEX = "index.html"


def _serve(root: Path, relative: str) -> Response:
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
    return FileResponse(
        target,
        media_type=media_type or "application/octet-stream",
        headers={
            # Generated code is untrusted, but the acceptance runner needs
            # same-origin DOM access, so framing is limited to our own origin
            # rather than blocked outright.
            "X-Frame-Options": "SAMEORIGIN",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/preview/{project_id}/{path:path}")
def preview(
    project_id: str, path: str, session: DbSession, user: OptionalUser
) -> Response:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在")
    owns = user is not None and project.user_id == user.id
    if not owns and project.slug is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在")

    # Race heats live under race/<heatId>/ inside the project directory.
    parts = path.strip("/").split("/", 2)
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
