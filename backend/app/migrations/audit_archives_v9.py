"""Offline immutable archive/recovery anchors; metadata is not proof of external IO."""
import hashlib
import json

from .audit_retention_v8 import SCHEMA as V8_SCHEMA, identifier


def digest(column):
    return f"length({column})=64 AND {column} NOT GLOB '*[^0-9a-f]*'"


SCHEMA = {
    'atom_schema_migrations': V8_SCHEMA['atom_schema_migrations'].replace(
        'CHECK(version IN (1,2,3,4,5,6,7,8))', 'CHECK(version IN (1,2,3,4,5,6,7,8,9))'),
    'security_audit_archives': f"""CREATE TABLE security_audit_archives (
        archive_id TEXT PRIMARY KEY NOT NULL CHECK({identifier('archive_id')}),
        operator_id TEXT NOT NULL CHECK({identifier('operator_id')}),
        policy_id TEXT NOT NULL REFERENCES security_audit_retention_policies(policy_id),
        policy_generation INTEGER NOT NULL CHECK(typeof(policy_generation)='integer' AND policy_generation>=1),
        archive_store_id TEXT NOT NULL CHECK({identifier('archive_store_id',64)}),
        format_version INTEGER NOT NULL CHECK(typeof(format_version)='integer' AND format_version=1),
        coverage TEXT NOT NULL CHECK(coverage='business_audit_events_v1'),
        scope_kind TEXT NOT NULL CHECK(scope_kind IN ('account','project')),
        scope_id TEXT NOT NULL CHECK({identifier('scope_id')}),
        event_kind TEXT NOT NULL,
        context_sha256 TEXT NOT NULL CHECK({digest('context_sha256')}),
        plan_sha256 TEXT NOT NULL CHECK({digest('plan_sha256')}),
        archive_sha256 TEXT NOT NULL CHECK({digest('archive_sha256')}),
        archive_bytes INTEGER NOT NULL CHECK(typeof(archive_bytes)='integer' AND archive_bytes BETWEEN 1 AND 262144),
        payload_sha256 TEXT NOT NULL CHECK({digest('payload_sha256')}),
        payload_bytes INTEGER NOT NULL CHECK(typeof(payload_bytes)='integer' AND payload_bytes>=1 AND payload_bytes<archive_bytes),
        event_count INTEGER NOT NULL CHECK(typeof(event_count)='integer' AND event_count BETWEEN 1 AND 100),
        after_sequence INTEGER NOT NULL CHECK(typeof(after_sequence)='integer' AND after_sequence>=0),
        upper_sequence INTEGER NOT NULL CHECK(typeof(upper_sequence)='integer' AND upper_sequence>after_sequence),
        observed_at INTEGER NOT NULL CHECK(typeof(observed_at)='integer' AND observed_at>=0),
        registered_at INTEGER NOT NULL CHECK(typeof(registered_at)='integer' AND registered_at>=observed_at),
        UNIQUE(archive_store_id,archive_sha256))""",
    'security_audit_archives_policy': 'CREATE INDEX security_audit_archives_policy ON security_audit_archives(policy_id,archive_id)',
    'security_audit_archives_consistent': """CREATE TRIGGER security_audit_archives_consistent BEFORE INSERT ON security_audit_archives
        WHEN NOT EXISTS(SELECT 1 FROM security_audit_retention_policies p WHERE p.policy_id=NEW.policy_id
            AND p.generation=NEW.policy_generation AND p.state='active' AND p.archive_store_id=NEW.archive_store_id
            AND p.scope_kind=NEW.scope_kind AND p.scope_id=NEW.scope_id AND p.event_kind=NEW.event_kind
            AND p.updated_at<=NEW.observed_at)
        OR EXISTS(SELECT 1 FROM security_audit_retention_holds h WHERE h.policy_id=NEW.policy_id AND h.state='active')
        BEGIN SELECT RAISE(ABORT,'inconsistent_archive_policy'); END""",
    'security_audit_archive_recoveries': f"""CREATE TABLE security_audit_archive_recoveries (
        recovery_id TEXT PRIMARY KEY NOT NULL CHECK({identifier('recovery_id')}),
        archive_id TEXT NOT NULL REFERENCES security_audit_archives(archive_id),
        verifier_id TEXT NOT NULL CHECK({identifier('verifier_id')}),
        archive_sha256 TEXT NOT NULL CHECK({digest('archive_sha256')}),
        payload_sha256 TEXT NOT NULL CHECK({digest('payload_sha256')}),
        event_count INTEGER NOT NULL CHECK(typeof(event_count)='integer' AND event_count BETWEEN 1 AND 100),
        verified_at INTEGER NOT NULL CHECK(typeof(verified_at)='integer' AND verified_at>=0))""",
    'security_audit_archive_recoveries_archive': 'CREATE INDEX security_audit_archive_recoveries_archive ON security_audit_archive_recoveries(archive_id,recovery_id)',
    'security_audit_archive_recoveries_consistent': """CREATE TRIGGER security_audit_archive_recoveries_consistent BEFORE INSERT ON security_audit_archive_recoveries
        WHEN NOT EXISTS(SELECT 1 FROM security_audit_archives a WHERE a.archive_id=NEW.archive_id
            AND a.archive_sha256=NEW.archive_sha256 AND a.payload_sha256=NEW.payload_sha256
            AND a.event_count=NEW.event_count AND a.registered_at<=NEW.verified_at)
        BEGIN SELECT RAISE(ABORT,'inconsistent_archive_recovery'); END""",
}
for table, key in (('security_audit_archives', 'archive_id'), ('security_audit_archive_recoveries', 'recovery_id')):
    for action in ('UPDATE', 'DELETE'):
        name = table+'_no_'+action.lower()
        SCHEMA[name] = f"""CREATE TRIGGER {name} BEFORE {action} ON {table}
            BEGIN SELECT RAISE(ABORT,'immutable_archive_evidence'); END"""
    collision = f'{key}=NEW.{key}'
    if table == 'security_audit_archives':
        collision += ' OR (archive_store_id=NEW.archive_store_id AND archive_sha256=NEW.archive_sha256)'
    name = table+'_no_replace'
    SCHEMA[name] = f"""CREATE TRIGGER {name} BEFORE INSERT ON {table}
        WHEN EXISTS(SELECT 1 FROM {table} WHERE {collision})
        BEGIN SELECT RAISE(ABORT,'existing_archive_evidence'); END"""

MIGRATION_HASH = hashlib.sha256(json.dumps(SCHEMA, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def apply(db):
    journal = db.execute('SELECT version,migration_hash,backup_sha256,applied_at FROM atom_schema_migrations').fetchall()
    db.execute('DROP TABLE atom_schema_migrations')
    for statement in SCHEMA.values():
        db.execute(statement)
    db.executemany('INSERT INTO atom_schema_migrations VALUES (?,?,?,?)', journal)
