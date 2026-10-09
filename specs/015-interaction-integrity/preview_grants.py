"""Operator acceptance: normal bounded preview grants, no console impersonation.

Run inside the exact serving API image. Output contains ephemeral credentials:
pipe directly to production_browser.py stdin, never log or persist output.
Existing owner/session/revision authorization is required by the repository.
Only preview access/audit records change, not projects, revisions or credits.
"""
import argparse
import json
from pathlib import Path
import sqlite3
import time

from app.config import get_settings
from app.preview_access import PreviewAccessRepository
from app.preview_cookie import preview_cookie_name
from app.preview_paths import view_root


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifacts', required=True, type=Path)
    args = parser.parse_args()
    settings = get_settings()
    access = PreviewAccessRepository(settings.db_path)
    rows = json.loads(args.artifacts.read_text())
    selected = []
    with sqlite3.connect(settings.db_path.as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        for expected in rows:
            row = db.execute('''SELECT p.user_id,w.current_revision_id,r.artifact_key,o.port
              FROM projects p JOIN revision_workspaces w ON w.project_id=p.id
              JOIN revision_records r ON r.id=w.current_revision_id
              JOIN project_origin_ports o ON o.project_id=p.id AND o.purpose='preview'
              WHERE p.id=? AND p.active_run_id IS NULL''', (expected['project'],)).fetchone()
            if row is None or row['current_revision_id'] != expected['revision'] or row['artifact_key'] != expected['artifact']:
                raise RuntimeError('acceptance_original_revision_changed')
            source = db.execute('''SELECT id FROM console_sessions WHERE user_id=?
              AND revoked_at IS NULL AND created_at<=? AND expires_at>?
              ORDER BY expires_at DESC LIMIT 1''', (row['user_id'], int(time.time()), int(time.time()) + 120)).fetchone()
            if source is None:
                raise RuntimeError('acceptance_active_owner_session_required')
            selected.append((expected, dict(row), source['id']))
    result = []
    for expected, row, session_id in selected:
        grant = access.issue(owner_id=row['user_id'], source_session_id=session_id,
                             project_id=expected['project'], revision_id=expected['revision'])
        session = access.exchange(project_id=expected['project'], handoff=grant.secret)
        origin = f'https://{settings.ip_preview_address}:{row["port"]}'
        result.append({**expected, 'url': origin + view_root(session.view_id),
                       'cookieName': preview_cookie_name(row['port']), 'cookie': session.secret,
                       'expires': session.expires_at, 'viewId': session.view_id})
    print(json.dumps({'console': settings.console_origin, 'previews': result}))


if __name__ == '__main__':
    main()
