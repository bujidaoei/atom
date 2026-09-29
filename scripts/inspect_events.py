"""Dump recent tool events so a failed build can be diagnosed from the record."""

from __future__ import annotations

import sqlite3
import sys

db = sqlite3.connect(sys.argv[1] if len(sys.argv) > 1 else "data/atom.db")
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10

rows = db.execute(
    "SELECT project_id, role, type, payload_json FROM run_events "
    "WHERE type LIKE 'tool.%' OR type LIKE 'run.%' "
    "ORDER BY id DESC LIMIT ?",
    (limit,),
).fetchall()

for project_id, role, kind, payload in rows:
    print(f"[{project_id[:8]}] {role or '-':<6} {kind}")
    print(f"    {payload[:600]}")
