"""Complete immutable planning documents and exact build approvals."""
import hashlib
import json

from .preview_access_v18 import SCHEMA as V18_SCHEMA


TABLES = {
    'contract_snapshots': '''CREATE TABLE contract_snapshots (
        id TEXT NOT NULL PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        version INTEGER NOT NULL CHECK(version>0),
        document_json TEXT NOT NULL CHECK(json_valid(document_json)),
        note TEXT NOT NULL,
        source_id TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(project_id,version), UNIQUE(project_id,id))''',
    'contract_snapshots_latest': '''CREATE INDEX contract_snapshots_latest
        ON contract_snapshots(project_id,version DESC)''',
    'contract_snapshots_source': '''CREATE TRIGGER contract_snapshots_source
        BEFORE INSERT ON contract_snapshots
        WHEN NEW.source_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM contract_snapshots WHERE project_id=NEW.project_id
            AND id=NEW.source_id AND version<NEW.version)
        BEGIN SELECT RAISE(ABORT,'invalid_contract_source'); END''',
    'contract_snapshots_immutable': '''CREATE TRIGGER contract_snapshots_immutable
        BEFORE UPDATE ON contract_snapshots
        BEGIN SELECT RAISE(ABORT,'immutable_contract'); END''',
    'contract_approvals': '''CREATE TABLE contract_approvals (
        job_id TEXT NOT NULL PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        snapshot_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(project_id,snapshot_id) REFERENCES contract_snapshots(project_id,id))''',
    'contract_approvals_immutable': '''CREATE TRIGGER contract_approvals_immutable
        BEFORE UPDATE ON contract_approvals
        BEGIN SELECT RAISE(ABORT,'immutable_contract_approval'); END''',
}
SCHEMA = {
    'atom_schema_migrations': V18_SCHEMA['atom_schema_migrations'].replace(
        '17,18))', '17,18,19))'),
    **TABLES,
}
MIGRATION_HASH = hashlib.sha256(json.dumps(SCHEMA, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def apply(db):
    journal = db.execute('SELECT version,migration_hash,backup_sha256,applied_at FROM atom_schema_migrations').fetchall()
    db.execute('DROP TABLE atom_schema_migrations')
    for statement in SCHEMA.values():
        db.execute(statement)
    db.executemany('INSERT INTO atom_schema_migrations VALUES (?,?,?,?)', journal)


def initialize_development(engine):
    """Unversioned local databases only; production uses the offline migration."""
    from sqlalchemy import inspect
    if 'contract_snapshots' not in inspect(engine).get_table_names():
        with engine.begin() as db:
            for statement in TABLES.values():
                db.exec_driver_sql(statement)
