"""Opaque publication bindings. A binding is a route identity, not authority."""
from dataclasses import dataclass
import re
import secrets
import sqlite3
import time

from .migrations import _schema
from .release_repository import PublishedArtifact, ReleaseRepository
from .verification_repository import VerificationError


@dataclass(frozen=True)
class ContentBinding:
    id: str
    project_id: str
    release_id: str


class ContentRepository:
    def __init__(self, path, *, lock_timeout=3):
        self._releases = ReleaseRepository(path,lock_timeout=lock_timeout)

    @staticmethod
    def _require_schema(db):
        db.row_factory = None
        version = _schema(db)
        db.row_factory = sqlite3.Row
        if version != 3:
            raise VerificationError('content_schema_required')

    def bind(self, *, owner: str, project_id: str, release_id: str) -> ContentBinding:
        if any(not isinstance(value,str) or re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',value) is None
               for value in (owner,project_id,release_id)):
            raise VerificationError('invalid_content_request')
        with self._releases._ledger._transaction() as db:
            self._require_schema(db)
            release = db.execute('''SELECT r.id FROM release_records r JOIN projects p ON p.id=r.project_id
                WHERE r.id=? AND r.project_id=? AND p.user_id=?''',(release_id,project_id,owner)).fetchone()
            if release is None:
                raise VerificationError('content_not_found')
            row = db.execute('SELECT * FROM content_bindings WHERE release_id=?',(release_id,)).fetchone()
            if row is not None:
                return ContentBinding(row['id'],row['project_id'],row['release_id'])
            identity = secrets.token_hex(16)
            db.execute('INSERT INTO content_bindings(id,project_id,release_id,purpose,created_at) VALUES (?,?,?,\'publication\',?)',
                       (identity,project_id,release_id,int(time.time())))
            return ContentBinding(identity,project_id,release_id)

    def resolve(self, *, binding_id: str, viewer: str | None = None) -> PublishedArtifact:
        if not isinstance(binding_id,str) or re.fullmatch(r'[0-9a-f]{32}',binding_id) is None:
            raise VerificationError('content_not_found')
        with self._releases._ledger._transaction() as db:
            self._require_schema(db)
            row = db.execute('''SELECT b.release_id,p.slug FROM content_bindings b
                JOIN release_publications p ON p.project_id=b.project_id WHERE b.id=?''',(binding_id,)).fetchone()
            if row is None:
                raise VerificationError('content_not_found')
            slug, release_id = row['slug'], row['release_id']
        # The immutable binding is captured above. Recheck current visibility
        # in the release ledger; no permission is inferred from knowing its ID.
        return self._releases.resolve(slug=slug,viewer=viewer,release_id=release_id)

    def sharing_binding(self, *, slug: str) -> ContentBinding:
        """Capture the current public route atomically; never allocate on GET."""
        if (not isinstance(slug,str) or len(slug)>63
                or re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',slug) is None):
            raise VerificationError('content_not_found')
        with self._releases._ledger._transaction() as db:
            self._require_schema(db)
            row = db.execute('''SELECT p.project_id,p.release_id,p.live,r.audience,b.id
                FROM release_publications p
                JOIN release_records r ON r.id=p.release_id AND r.project_id=p.project_id
                LEFT JOIN content_bindings b ON b.release_id=r.id AND b.project_id=p.project_id
                WHERE p.slug=?''',(slug,)).fetchone()
            if row is None or not row['live'] or row['audience'] != 'public':
                raise VerificationError('content_not_found')
            if row['id'] is None:
                raise VerificationError('content_binding_unavailable')
            return ContentBinding(row['id'],row['project_id'],row['release_id'])
