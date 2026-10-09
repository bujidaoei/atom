"""Read-only logical receipts for the screenshot projects and their history."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--artifacts', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args()
    expected = json.loads(args.artifacts.read_text(encoding='utf-8'))
    results = []
    with sqlite3.connect(args.database.as_uri() + '?mode=ro', uri=True) as db:
        db.execute('BEGIN')
        for row in expected:
            head = db.execute('''SELECT w.current_revision_id,r.artifact_key
                FROM revision_workspaces w JOIN revision_records r ON r.id=w.current_revision_id
                WHERE w.project_id=?''', (row['project'],)).fetchone()
            assert head == (row['revision'], row['artifact'])
            captured = {}
            for table in ('projects', 'messages', 'requirements', 'runs', 'revision_workspaces', 'revision_records'):
                column = 'id' if table == 'projects' else 'project_id'
                values = db.execute(f'SELECT * FROM {table} WHERE {column}=?', (row['project'],)).fetchall()
                payload = json.dumps(sorted(values, key=repr), separators=(',', ':'), ensure_ascii=True).encode()
                captured[table] = {'rows': len(values), 'sha256': hashlib.sha256(payload).hexdigest()}
            results.append({**row, 'logicalRows': captured})
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        db.rollback()
    if args.compare:
        assert results == json.loads(args.compare.read_text(encoding='utf-8')), 'original_project_data_changed'
    args.output.write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps({'projects': len(results), 'unchanged': bool(args.compare), 'foreignKeyErrors': 0}))


if __name__ == '__main__':
    main()
