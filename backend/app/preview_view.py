"""Byte-verified materialization of one authorized saved preview revision."""
from contextlib import contextmanager
from dataclasses import dataclass
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore

from .artifacts import ArtifactError, SnapshotStore
from .content_policy import validate_content_manifest
from .preview_access import PreviewAccessError, PreviewAccessRepository, PreviewRevision
from .snapshots import SnapshotError, receive_snapshot, verify_snapshot


_READS = BoundedSemaphore(1)


@dataclass(frozen=True)
class PreviewView:
    revision: PreviewRevision
    path: Path


@contextmanager
def materialized_preview(access: PreviewAccessRepository, store: SnapshotStore, *,
                         project_id: str, session_secret: str):
    if not _READS.acquire(timeout=3):
        raise PreviewAccessError('preview_capacity')
    try:
        revision = access.authorize(project_id=project_id, session_secret=session_secret)
        payload = store.read(revision.artifact.key)
        try:
            manifest = verify_snapshot(io.BytesIO(payload))
            if (len(payload) != revision.artifact.size
                    or manifest.revision != revision.artifact.revision):
                raise ArtifactError('preview_artifact_mismatch')
            validate_content_manifest(manifest)
        except SnapshotError:
            raise ArtifactError('preview_artifact_mismatch') from None
        if access.authorize(project_id=project_id, session_secret=session_secret) != revision:
            raise PreviewAccessError('preview_access_denied')
        with TemporaryDirectory(prefix='atom-preview-') as temporary:
            received = receive_snapshot(io.BytesIO(payload), Path(temporary))
            if access.authorize(project_id=project_id, session_secret=session_secret) != revision:
                raise PreviewAccessError('preview_access_denied')
            yield PreviewView(revision, received.path)
    finally:
        _READS.release()
