"""Immutable content-origin bindings; no DNS or serving side effects."""
import hashlib
import json

from .release_v2 import JOURNAL as V2_JOURNAL

SCHEMA = {
    'atom_schema_migrations': V2_JOURNAL.replace('CHECK(version IN (1,2))','CHECK(version IN (1,2,3))'),
    'content_bindings': """CREATE TABLE content_bindings (
        id TEXT NOT NULL PRIMARY KEY CHECK(length(id)=32 AND id NOT GLOB '*[^0-9a-f]*'),
        project_id TEXT NOT NULL, release_id TEXT NOT NULL UNIQUE,
        purpose TEXT NOT NULL CHECK(purpose='publication'), created_at INTEGER NOT NULL,
        FOREIGN KEY(release_id,project_id) REFERENCES release_records(id,project_id))""",
}
for operation in ('UPDATE','DELETE'):
    name = 'content_bindings_no_' + operation.lower()
    SCHEMA[name] = f"CREATE TRIGGER {name} BEFORE {operation} ON content_bindings BEGIN SELECT RAISE(ABORT,'immutable_content_binding'); END"

MIGRATION_HASH = hashlib.sha256(json.dumps(SCHEMA,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def apply(db):
    journal = db.execute('SELECT version,migration_hash,backup_sha256,applied_at FROM atom_schema_migrations').fetchall()
    db.execute('DROP TABLE atom_schema_migrations')
    for statement in SCHEMA.values():
        db.execute(statement)
    db.executemany('INSERT INTO atom_schema_migrations VALUES (?,?,?,?)',journal)
