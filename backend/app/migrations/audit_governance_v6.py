"""Offline destination obligation registry; runtime governance is enabled separately."""
import hashlib
import json
import sqlite3
import time

from .audit_v5 import SCHEMA as V5_SCHEMA


SCHEMA = {
    'atom_schema_migrations': V5_SCHEMA['atom_schema_migrations'].replace(
        'CHECK(version IN (1,2,3,4,5))', 'CHECK(version IN (1,2,3,4,5,6))'),
    'security_audit_destinations': """CREATE TABLE security_audit_destinations (
        destination_id TEXT PRIMARY KEY NOT NULL CHECK(length(destination_id) BETWEEN 1 AND 64 AND destination_id NOT GLOB '*[^A-Za-z0-9_.-]*'),
        scope_kind TEXT NOT NULL CHECK(scope_kind IN ('account','project')),
        scope_id TEXT NOT NULL CHECK(length(scope_id) BETWEEN 1 AND 100 AND scope_id NOT GLOB '*[^A-Za-z0-9_.-]*'),
        generation INTEGER NOT NULL CHECK(typeof(generation)='integer' AND generation>=1),
        state TEXT NOT NULL CHECK(state IN ('unconfigured','active','paused','blocked','retired')),
        created_at INTEGER NOT NULL CHECK(typeof(created_at)='integer' AND created_at>=0),
        updated_at INTEGER NOT NULL CHECK(typeof(updated_at)='integer' AND updated_at>=created_at),
        blocked_reason TEXT CHECK(blocked_reason IS NULL OR blocked_reason IN ('receiver_configuration','invalid_payload')),
        blocked_at INTEGER CHECK(blocked_at IS NULL OR (typeof(blocked_at)='integer' AND blocked_at>=created_at AND blocked_at<=updated_at)),
        required_through_sequence INTEGER CHECK(required_through_sequence IS NULL OR (typeof(required_through_sequence)='integer' AND required_through_sequence>=0)),
        CHECK((state='blocked' AND blocked_reason IS NOT NULL AND blocked_at IS NOT NULL) OR
              (state<>'blocked' AND blocked_reason IS NULL AND blocked_at IS NULL)),
        CHECK((state='retired' AND required_through_sequence IS NOT NULL) OR
              (state<>'retired' AND required_through_sequence IS NULL)))""",
    'security_audit_destinations_scope': 'CREATE INDEX security_audit_destinations_scope ON security_audit_destinations(scope_kind,scope_id,state,destination_id)',
    'security_audit_destinations_identity': """CREATE TRIGGER security_audit_destinations_identity BEFORE UPDATE OF destination_id,scope_kind,scope_id,created_at ON security_audit_destinations
        BEGIN SELECT RAISE(ABORT,'immutable_audit_destination'); END""",
    'security_audit_destinations_generation': """CREATE TRIGGER security_audit_destinations_generation BEFORE UPDATE ON security_audit_destinations
        WHEN NEW.generation<>OLD.generation+1 OR NEW.updated_at<OLD.updated_at OR OLD.state='retired'
        BEGIN SELECT RAISE(ABORT,'invalid_audit_destination_transition'); END""",
    'security_audit_destinations_no_delete': """CREATE TRIGGER security_audit_destinations_no_delete BEFORE DELETE ON security_audit_destinations
        BEGIN SELECT RAISE(ABORT,'retained_audit_destination'); END""",
    'security_audit_destinations_no_replace': """CREATE TRIGGER security_audit_destinations_no_replace BEFORE INSERT ON security_audit_destinations
        WHEN EXISTS(SELECT 1 FROM security_audit_destinations WHERE destination_id=NEW.destination_id)
        BEGIN SELECT RAISE(ABORT,'existing_audit_destination'); END""",
    'security_audit_delivery_registry_insert': """CREATE TRIGGER security_audit_delivery_registry_insert BEFORE INSERT ON security_audit_delivery
        WHEN NOT EXISTS(SELECT 1 FROM security_audit_destinations r JOIN security_audit_events e ON e.event_id=NEW.event_id
            WHERE r.destination_id=NEW.destination_id AND r.scope_kind=e.scope_kind AND r.scope_id=e.scope_id AND r.state='active')
        BEGIN SELECT RAISE(ABORT,'audit_destination_not_active'); END""",
    'security_audit_delivery_registry_claim': """CREATE TRIGGER security_audit_delivery_registry_claim BEFORE UPDATE ON security_audit_delivery
        WHEN NEW.state='leased' AND NOT EXISTS(SELECT 1 FROM security_audit_destinations r JOIN security_audit_events e ON e.event_id=NEW.event_id
            WHERE r.destination_id=NEW.destination_id AND r.scope_kind=e.scope_kind AND r.scope_id=e.scope_id AND r.state='active')
        BEGIN SELECT RAISE(ABORT,'audit_destination_not_active'); END""",
}
MIGRATION_HASH = hashlib.sha256(json.dumps(SCHEMA, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def apply(db):
    # Historical rows are authoritative even when their destination has left process config.
    conflicts = db.execute('SELECT destination_id FROM (SELECT DISTINCT d.destination_id,e.scope_kind,e.scope_id '
        'FROM security_audit_delivery d JOIN security_audit_events e ON e.event_id=d.event_id) '
        'GROUP BY destination_id HAVING count(*)>1 LIMIT 1').fetchone()
    if conflicts:
        raise sqlite3.IntegrityError('conflicting_historical_audit_scope')
    journal = db.execute('SELECT version,migration_hash,backup_sha256,applied_at FROM atom_schema_migrations').fetchall()
    db.execute('DROP TABLE atom_schema_migrations')
    for statement in SCHEMA.values():
        db.execute(statement)
    db.executemany('INSERT INTO atom_schema_migrations VALUES (?,?,?,?)', journal)
    now = int(time.time())
    db.execute('INSERT INTO security_audit_destinations '
        '(destination_id,scope_kind,scope_id,generation,state,created_at,updated_at) '
        "SELECT DISTINCT d.destination_id,e.scope_kind,e.scope_id,1,'unconfigured',?,? "
        'FROM security_audit_delivery d JOIN security_audit_events e ON e.event_id=d.event_id', (now, now))
