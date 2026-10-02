"""Offline index for bounded latest-verification reads."""
import hashlib
import json

from .rollback_v14 import SCHEMA as V14


INDEX = 'verification_requests_project_latest'
SCHEMA = {
    'atom_schema_migrations': V14['atom_schema_migrations'].replace(
        'CHECK(version IN (1,2,3,4,5,6,7,8,9,10,11,12,13,14))',
        'CHECK(version IN (1,2,3,4,5,6,7,8,9,10,11,12,13,14,15))'),
    INDEX: f'CREATE INDEX {INDEX} ON verification_requests(project_id,created_at DESC,id DESC)',
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
