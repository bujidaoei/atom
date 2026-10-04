"""Bounded owner-only reads of retained publication snapshots."""
from contextlib import closing
from datetime import datetime, timezone
import re
import sqlite3

from .verification_repository import VerificationError

_IDENTITY = re.compile(r'[A-Za-z0-9_.-]{1,100}\Z')
_CURSOR = re.compile(r'[1-9][0-9]{0,18}\Z')


def publication_history(path, *, owner: str, project_id: str,
                        limit: int = 20, cursor: str | None = None, timeout: float = 3) -> dict:
    if (any(type(value) is not str or _IDENTITY.fullmatch(value) is None
            for value in (owner, project_id)) or type(limit) is not int or not 1 <= limit <= 50
            or (cursor is not None and (type(cursor) is not str or _CURSOR.fullmatch(cursor) is None
                                       or int(cursor) >= 2**63))):
        raise VerificationError('invalid_release_request')
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=timeout)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            if db.execute('PRAGMA user_version').fetchone()[0] not in (16, 17, 18, 19):
                raise VerificationError('publication_policy_schema_required')
            if db.execute('SELECT 1 FROM projects WHERE id=? AND user_id=?', (project_id, owner)).fetchone() is None:
                raise VerificationError('release_not_found')
            parameters = [project_id]
            before = ''
            if cursor is not None:
                before = ' AND r.publication_generation<?'
                parameters.append(int(cursor))
            parameters.append(limit + 1)
            rows = db.execute('''SELECT r.id,r.revision_id,r.created_at,r.audience,r.publication_generation,
                r.verification_mode,r.verification_id,b.id AS binding_id,
                p.release_id AS current_release,p.live,s.source_release_id
                FROM release_records r
                LEFT JOIN content_bindings b ON b.release_id=r.id AND b.project_id=r.project_id
                LEFT JOIN release_publications p ON p.project_id=r.project_id
                LEFT JOIN release_rollback_sources s ON s.new_release_id=r.id AND s.project_id=r.project_id
                WHERE r.project_id=?''' + before +
                ' ORDER BY r.publication_generation DESC LIMIT ?', parameters).fetchall()
            items = []
            for row in rows[:limit]:
                if row['binding_id'] is None:
                    raise VerificationError('release_corrupt')
                items.append({
                    'releaseId': row['id'], 'revisionId': row['revision_id'],
                    'version': row['publication_generation'],
                    'createdAt': datetime.fromtimestamp(row['created_at'], timezone.utc).isoformat(),
                    'audience': row['audience'], 'verificationMode': row['verification_mode'],
                    'verificationId': row['verification_id'], 'bindingId': row['binding_id'],
                    'isLive': bool(row['live'] and row['current_release'] == row['id']),
                    'restoredFrom': row['source_release_id'],
                })
            next_cursor = None
            if len(rows) > limit:
                last = rows[limit - 1]
                next_cursor = str(last['publication_generation'])
            return {'items': items, 'nextCursor': next_cursor}
    except (sqlite3.Error, OSError):
        raise VerificationError('release_unavailable') from None
    except (ValueError, OverflowError):
        raise VerificationError('release_corrupt') from None
