"""Private read views of committed artifacts, independent of legacy workspaces."""
from contextlib import contextmanager
from dataclasses import dataclass
import io
from pathlib import Path
from tempfile import TemporaryDirectory

from .artifacts import ArtifactStore
from .revisions import RevisionError, RevisionRepository, WorkspaceRevision
from .snapshots import receive_snapshot, verify_snapshot


@dataclass(frozen=True)
class RevisionView:
    revision: WorkspaceRevision
    path: Path


@contextmanager
def materialized_revision(repository: RevisionRepository, store: ArtifactStore, *,
                          owner: str, workspace_id: str, expected_revision_id: str | None = None):
    """Pin verified bytes for the scope; never promote or modify a workspace."""
    revision = repository.current_revision(owner, workspace_id)
    if revision is None:
        raise RevisionError('revision_not_initialized')
    if expected_revision_id is not None and revision.revision_id != expected_revision_id:
        raise RevisionError('revision_conflict')
    payload, _ = verified_revision_payload(store, revision)
    with TemporaryDirectory(prefix='atom-revision-') as temporary:
        received = receive_snapshot(io.BytesIO(payload), Path(temporary))
        yield RevisionView(revision, received.path)


def verified_revision_payload(store: ArtifactStore, revision: WorkspaceRevision):
    payload = store.read(revision.artifact.key)
    verified = verify_snapshot(io.BytesIO(payload))
    if len(payload) != revision.artifact.size or verified.revision != revision.artifact.revision:
        raise RevisionError('revision_artifact_mismatch')
    return payload, verified
