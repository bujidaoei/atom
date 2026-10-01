"""Distinct immutable isolation evidence; never upgrades historical recovery rows."""
import hashlib
import json

from .audit_archives_v9 import SCHEMA as V9_SCHEMA, digest, identifier


TABLE = 'security_audit_isolated_recoveries'
SCHEMA = {
    'atom_schema_migrations': V9_SCHEMA['atom_schema_migrations'].replace(
        'CHECK(version IN (1,2,3,4,5,6,7,8,9))', 'CHECK(version IN (1,2,3,4,5,6,7,8,9,10))'),
    TABLE: f"""CREATE TABLE {TABLE} (
        recovery_id TEXT PRIMARY KEY NOT NULL CHECK({identifier('recovery_id')}),
        archive_id TEXT NOT NULL REFERENCES security_audit_archives(archive_id),
        verifier_id TEXT NOT NULL CHECK({identifier('verifier_id')}),
        protocol TEXT NOT NULL CHECK(protocol='audit-recovery-v2'),
        image TEXT NOT NULL CHECK(length(image)=71 AND substr(image,1,7)='sha256:' AND substr(image,8) NOT GLOB '*[^0-9a-f]*'),
        policy_digest TEXT NOT NULL CHECK({digest('policy_digest')}),
        attempt_id TEXT NOT NULL CHECK(length(attempt_id)=32 AND attempt_id NOT GLOB '*[^0-9a-f]*'),
        archive_sha256 TEXT NOT NULL CHECK({digest('archive_sha256')}),
        payload_sha256 TEXT NOT NULL CHECK({digest('payload_sha256')}),
        event_count INTEGER NOT NULL CHECK(typeof(event_count)='integer' AND event_count BETWEEN 1 AND 100),
        result_sha256 TEXT NOT NULL CHECK({digest('result_sha256')}),
        verified_at INTEGER NOT NULL CHECK(typeof(verified_at)='integer' AND verified_at>=0),
        UNIQUE(verifier_id,attempt_id))""",
    TABLE+'_archive': f'CREATE INDEX {TABLE}_archive ON {TABLE}(archive_id,recovery_id)',
    TABLE+'_consistent': f"""CREATE TRIGGER {TABLE}_consistent BEFORE INSERT ON {TABLE}
        WHEN NOT EXISTS(SELECT 1 FROM security_audit_archives a WHERE a.archive_id=NEW.archive_id
            AND a.archive_sha256=NEW.archive_sha256 AND a.payload_sha256=NEW.payload_sha256
            AND a.event_count=NEW.event_count AND a.registered_at<=NEW.verified_at)
        BEGIN SELECT RAISE(ABORT,'inconsistent_isolated_recovery'); END""",
    TABLE+'_no_replace': f"""CREATE TRIGGER {TABLE}_no_replace BEFORE INSERT ON {TABLE}
        WHEN EXISTS(SELECT 1 FROM {TABLE} WHERE recovery_id=NEW.recovery_id
            OR (verifier_id=NEW.verifier_id AND attempt_id=NEW.attempt_id))
        BEGIN SELECT RAISE(ABORT,'existing_isolated_recovery'); END""",
}
for action in ('UPDATE', 'DELETE'):
    name = TABLE+'_no_'+action.lower()
    SCHEMA[name] = f"""CREATE TRIGGER {name} BEFORE {action} ON {TABLE}
        BEGIN SELECT RAISE(ABORT,'immutable_isolated_recovery'); END"""

MIGRATION_HASH = hashlib.sha256(json.dumps(SCHEMA, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def apply(db):
    journal = db.execute('SELECT version,migration_hash,backup_sha256,applied_at FROM atom_schema_migrations').fetchall()
    db.execute('DROP TABLE atom_schema_migrations')
    for statement in SCHEMA.values():
        db.execute(statement)
    db.executemany('INSERT INTO atom_schema_migrations VALUES (?,?,?,?)', journal)
