from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from .config import get_settings

# Files the agent may leave behind that should never be served or listed.
_HIDDEN_PREFIXES = (".git", ".pi", "node_modules", "__pycache__")


def project_root(project_id: str) -> Path:
    return get_settings().projects_dir / project_id


def workspace_dir(project_id: str, heat_id: str | None = None) -> Path:
    root = project_root(project_id)
    return root / "race" / heat_id / "workspace" if heat_id else root / "workspace"


def sessions_dir(project_id: str) -> Path:
    return project_root(project_id) / "sessions"


def agent_dir(project_id: str) -> Path:
    return project_root(project_id) / "agent"


def published_dir(slug: str) -> Path:
    return get_settings().published_dir / slug


def ensure_project_dirs(project_id: str) -> None:
    for path in (workspace_dir(project_id), sessions_dir(project_id), agent_dir(project_id)):
        path.mkdir(parents=True, exist_ok=True)


def remove_project_dirs(project_id: str) -> None:
    shutil.rmtree(project_root(project_id), ignore_errors=True)


def _is_hidden(relative: Path) -> bool:
    return any(part.startswith(_HIDDEN_PREFIXES) for part in relative.parts)


def list_files(root: Path) -> list[dict[str, object]]:
    """Flat listing of a workspace, sorted so index.html leads."""
    if not root.is_dir():
        return []
    entries: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if _is_hidden(relative):
            continue
        stat = path.stat()
        entries.append(
            {
                "path": relative.as_posix(),
                "bytes": stat.st_size,
                "updatedAt": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            }
        )
    entries.sort(key=lambda entry: (str(entry["path"]) != "index.html", entry["path"]))
    return entries


def workspace_stats(root: Path) -> tuple[int, int]:
    files = list_files(root)
    return len(files), sum(int(entry["bytes"]) for entry in files)


def resolve_within(root: Path, relative: str) -> Path | None:
    """Resolve a client-supplied path, refusing anything that escapes ``root``.

    Both sides are fully resolved first so symlinks and ``..`` segments cannot
    be used to read outside the workspace.
    """
    if not relative or relative.startswith("/") or "\x00" in relative:
        return None
    try:
        base = root.resolve(strict=False)
        target = (base / relative).resolve(strict=False)
        target.relative_to(base)
    except (ValueError, OSError):
        return None
    if _is_hidden(Path(relative)):
        return None
    return target


def copy_tree(source: Path, destination: Path) -> None:
    """Replace ``destination`` with a copy of ``source``."""
    shutil.rmtree(destination, ignore_errors=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        destination.mkdir(parents=True, exist_ok=True)
