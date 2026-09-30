"""Verified private materialization of an authorized, pinned publication."""
from contextlib import contextmanager
from dataclasses import dataclass
import io
from pathlib import Path
from tempfile import TemporaryDirectory

from .artifacts import ArtifactError, ArtifactStore
from .release_repository import PublishedArtifact, ReleaseRepository
from .snapshots import receive_snapshot, verify_snapshot


@dataclass(frozen=True)
class ReleaseView:
    publication: PublishedArtifact
    path: Path


@contextmanager
def materialized_release(repository: ReleaseRepository, store: ArtifactStore, *,
                         slug: str, viewer: str | None = None, release_id: str | None = None):
    publication = repository.resolve(slug=slug, viewer=viewer, release_id=release_id)
    payload = store.read(publication.artifact.key)
    manifest = verify_snapshot(io.BytesIO(payload))
    if len(payload) != publication.artifact.size or manifest.revision != publication.artifact.revision:
        raise ArtifactError('release_artifact_mismatch')
    # Authorization may have changed during IO; do not switch a captured version
    # to a newly published version while completing the read.
    repository.resolve(slug=slug, viewer=viewer, release_id=publication.release_id)
    with TemporaryDirectory(prefix='atom-release-') as temporary:
        received = receive_snapshot(io.BytesIO(payload), Path(temporary))
        yield ReleaseView(publication, received.path)
