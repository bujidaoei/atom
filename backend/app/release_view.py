"""Verified private materialization of an authorized, pinned publication."""
from contextlib import contextmanager
from dataclasses import dataclass
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore

from .artifacts import ArtifactError, ArtifactStore
from .content_policy import validate_content_manifest
from .release_repository import PublishedArtifact, ReleaseRepository
from .snapshots import receive_snapshot, verify_snapshot
from .verification_repository import VerificationError

_READS = BoundedSemaphore(1)


@dataclass(frozen=True)
class ReleaseView:
    publication: PublishedArtifact
    path: Path


@contextmanager
def materialized_release(repository: ReleaseRepository, store: ArtifactStore, *,
                         slug: str, viewer: str | None = None, release_id: str | None = None):
    def resolve(captured=None):
        return repository.resolve(slug=slug,viewer=viewer,
                                  release_id=captured.release_id if captured else release_id)
    with _admitted(resolve,store) as view:
        yield view


@contextmanager
def materialized_content(repository, store: ArtifactStore, *, binding_id: str, viewer: str | None = None):
    def resolve(captured=None):
        return repository.resolve(binding_id=binding_id,viewer=viewer)
    with _admitted(resolve,store) as view:
        yield view


@contextmanager
def materialized_private_content(repository, access, store: ArtifactStore, *, binding_id: str, session_secret: str):
    def resolve(captured=None):
        principal=access.authorize(binding_id=binding_id,session_secret=session_secret)
        return repository.resolve(binding_id=binding_id,viewer=principal.viewer_id)
    with _admitted(resolve,store) as view:
        yield view


@contextmanager
def _admitted(resolve,store):
    if not _READS.acquire(timeout=3):
        raise VerificationError('release_capacity')
    try:
        with _materialize(resolve,store) as view:
            yield view
    finally:
        _READS.release()


@contextmanager
def _materialize(resolve,store):
    publication = resolve()
    payload = store.read(publication.artifact.key)
    manifest = verify_snapshot(io.BytesIO(payload))
    if len(payload) != publication.artifact.size or manifest.revision != publication.artifact.revision:
        raise ArtifactError('release_artifact_mismatch')
    validate_content_manifest(manifest)
    # Authorization may have changed during IO; do not switch a captured version
    # to a newly published version while completing the read.
    resolve(publication)
    with TemporaryDirectory(prefix='atom-release-') as temporary:
        received = receive_snapshot(io.BytesIO(payload), Path(temporary))
        resolve(publication)
        yield ReleaseView(publication, received.path)
