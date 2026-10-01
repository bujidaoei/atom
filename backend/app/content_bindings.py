"""Binding allocation inside an already authorized v3 writer transaction."""
from dataclasses import dataclass
import secrets
import time


@dataclass(frozen=True)
class ContentBinding:
    id: str
    project_id: str
    release_id: str


def ensure_binding(db, *, project_id: str, release_id: str) -> ContentBinding:
    """Caller owns schema verification, scope authorization and commit/rollback."""
    row = db.execute('SELECT * FROM content_bindings WHERE release_id=? AND project_id=?',
                     (release_id,project_id)).fetchone()
    if row is not None:
        return ContentBinding(row['id'],row['project_id'],row['release_id'])
    identity = secrets.token_hex(16)
    db.execute("INSERT INTO content_bindings(id,project_id,release_id,purpose,created_at) VALUES (?,?,?,'publication',?)",
               (identity,project_id,release_id,int(time.time())))
    return ContentBinding(identity,project_id,release_id)
