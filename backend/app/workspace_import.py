"""Trusted offline import of quiescent legacy workspaces into immutable storage.

The caller must stop legacy writers and supply a trusted workspace path; this is
not an HTTP endpoint and does not accept runtime/model paths.
"""
from dataclasses import dataclass
import io
from pathlib import Path

from .artifacts import Artifact, ArtifactStore
from .revisions import RevisionError, RevisionRepository
from .snapshots import export_snapshot


@dataclass(frozen=True)
class ImportedWorkspace:
    workspace_id: str
    revision_id: str
    artifact: Artifact


def import_workspace(repository: RevisionRepository, store: ArtifactStore, *,
                     owner: str, project_id: str, source: Path,
                     heat_id: str | None = None) -> ImportedWorkspace:
    workspace = repository.ensure_workspace(owner, project_id, heat_id)
    source = Path(source)
    if not source.is_absolute():
        raise RevisionError('invalid_import_source')
    try:
        resolved = source.resolve(strict=True)
        if (resolved.is_relative_to(store.root.resolve())
                or any(path.resolve().is_relative_to(resolved) for path in (repository.path, store.root))):
            raise RevisionError('invalid_import_source')
    except (OSError, RuntimeError):
        raise RevisionError('invalid_import_source') from None
    stream = io.BytesIO()
    export_snapshot(source, stream)
    artifact = store.put(stream.getvalue())
    revision = repository.bootstrap(owner, workspace, artifact)
    return ImportedWorkspace(workspace, revision, artifact)
