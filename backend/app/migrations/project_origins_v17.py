"""Immutable project-origin port reservations; offline schema only."""
import hashlib
import json

from .publication_policy_v16 import SCHEMA as V16_SCHEMA


SCHEMA = {
    'atom_schema_migrations': V16_SCHEMA['atom_schema_migrations'].replace(
        'CHECK(version IN (1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16))',
        'CHECK(version IN (1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17))'),
    'project_origin_ports': '''CREATE TABLE project_origin_ports (
        project_id TEXT NOT NULL,
        purpose TEXT NOT NULL CHECK(purpose IN ('preview','public')),
        port INTEGER NOT NULL CHECK(typeof(port)='integer' AND port BETWEEN 1024 AND 65535),
        created_at INTEGER NOT NULL CHECK(typeof(created_at)='integer' AND created_at>=0),
        PRIMARY KEY(project_id,purpose), UNIQUE(port))''',
    'project_origin_ports_project': '''CREATE TRIGGER project_origin_ports_project
        BEFORE INSERT ON project_origin_ports
        WHEN NOT EXISTS (SELECT 1 FROM projects WHERE id=NEW.project_id)
        BEGIN SELECT RAISE(ABORT,'origin_project_missing'); END''',
    'project_origin_ports_no_update': '''CREATE TRIGGER project_origin_ports_no_update
        BEFORE UPDATE ON project_origin_ports
        BEGIN SELECT RAISE(ABORT,'immutable_project_origin'); END''',
    'project_origin_ports_no_delete': '''CREATE TRIGGER project_origin_ports_no_delete
        BEFORE DELETE ON project_origin_ports
        BEGIN SELECT RAISE(ABORT,'immutable_project_origin'); END''',
    'projects_no_origin_reuse': '''CREATE TRIGGER projects_no_origin_reuse
        BEFORE INSERT ON projects
        WHEN EXISTS (SELECT 1 FROM project_origin_ports WHERE project_id=NEW.id)
        BEGIN SELECT RAISE(ABORT,'reserved_project_identity'); END''',
}

MIGRATION_HASH = hashlib.sha256(json.dumps(SCHEMA, sort_keys=True,
                                           separators=(',', ':')).encode()).hexdigest()


def apply(db):
    journal = db.execute('SELECT version,migration_hash,backup_sha256,applied_at '
                         'FROM atom_schema_migrations').fetchall()
    db.execute('DROP TABLE atom_schema_migrations')
    for statement in SCHEMA.values():
        db.execute(statement)
    db.executemany('INSERT INTO atom_schema_migrations VALUES (?,?,?,?)', journal)
