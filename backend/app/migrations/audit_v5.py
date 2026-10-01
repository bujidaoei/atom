"""Explicit offline audit ledger schema; business writers are enabled separately."""
import hashlib
import json
from .access_v4 import SCHEMA as V4_SCHEMA


def identity(column):
    return f"length({column})=32 AND {column} NOT GLOB '*[^0-9a-f]*'"


SCHEMA = {
    'atom_schema_migrations': V4_SCHEMA['atom_schema_migrations'].replace('CHECK(version IN (1,2,3,4))','CHECK(version IN (1,2,3,4,5))'),
    'security_audit_events': f"""CREATE TABLE security_audit_events (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL UNIQUE CHECK({identity('event_id')}),
        schema_version INTEGER NOT NULL CHECK(schema_version=1),
        event_kind TEXT NOT NULL CHECK(event_kind IN ('console.session.created','console.session.revoked',
            'console.account_sessions.revoked','content.handoff.issued','content.session.created',
            'release.published','release.unpublished')),
        occurred_at INTEGER NOT NULL CHECK(typeof(occurred_at)='integer' AND occurred_at>=0),
        actor_kind TEXT NOT NULL CHECK(actor_kind IN ('user','system')),
        actor_id TEXT CHECK(actor_id IS NULL OR (length(actor_id) BETWEEN 1 AND 100 AND actor_id NOT GLOB '*[^A-Za-z0-9_.-]*')),
        scope_kind TEXT NOT NULL CHECK(scope_kind IN ('account','project')),
        scope_id TEXT NOT NULL CHECK(length(scope_id) BETWEEN 1 AND 100 AND scope_id NOT GLOB '*[^A-Za-z0-9_.-]*'),
        operation_id TEXT CHECK(operation_id IS NULL OR length(operation_id) BETWEEN 1 AND 100),
        source_session_id TEXT CHECK(source_session_id IS NULL OR ({identity('source_session_id')})),
        binding_id TEXT CHECK(binding_id IS NULL OR ({identity('binding_id')})),
        release_id TEXT CHECK(release_id IS NULL OR length(release_id) BETWEEN 1 AND 100),
        revision_id TEXT CHECK(revision_id IS NULL OR length(revision_id) BETWEEN 1 AND 100),
        publication_generation INTEGER CHECK(publication_generation IS NULL OR (typeof(publication_generation)='integer' AND publication_generation>0)),
        affected_count INTEGER CHECK(affected_count IS NULL OR (typeof(affected_count)='integer' AND affected_count BETWEEN 1 AND 128)),
        CHECK((actor_kind='user' AND actor_id IS NOT NULL) OR (actor_kind='system' AND actor_id IS NULL)))""",
    'security_audit_scope_sequence': 'CREATE INDEX security_audit_scope_sequence ON security_audit_events(scope_kind,scope_id,sequence)',
    'security_audit_time_sequence': 'CREATE INDEX security_audit_time_sequence ON security_audit_events(occurred_at,sequence)',
    'security_audit_no_update': """CREATE TRIGGER security_audit_no_update BEFORE UPDATE ON security_audit_events
        BEGIN SELECT RAISE(ABORT,'immutable_audit_event'); END""",
    'security_audit_no_delete': """CREATE TRIGGER security_audit_no_delete BEFORE DELETE ON security_audit_events
        BEGIN SELECT RAISE(ABORT,'immutable_audit_event'); END""",
    'security_audit_no_replace': """CREATE TRIGGER security_audit_no_replace BEFORE INSERT ON security_audit_events
        WHEN EXISTS(SELECT 1 FROM security_audit_events WHERE event_id=NEW.event_id OR sequence=NEW.sequence)
        BEGIN SELECT RAISE(ABORT,'immutable_audit_event'); END""",
    'security_audit_delivery': f"""CREATE TABLE security_audit_delivery (
        event_id TEXT NOT NULL REFERENCES security_audit_events(event_id),
        destination_id TEXT NOT NULL CHECK(length(destination_id) BETWEEN 1 AND 64 AND destination_id NOT GLOB '*[^A-Za-z0-9_.-]*'),
        state TEXT NOT NULL CHECK(state IN ('pending','leased','delivered')),
        attempt INTEGER NOT NULL DEFAULT 0 CHECK(typeof(attempt)='integer' AND attempt>=0),
        next_attempt_at INTEGER NOT NULL CHECK(typeof(next_attempt_at)='integer' AND next_attempt_at>=0),
        lease_owner TEXT CHECK(lease_owner IS NULL OR ({identity('lease_owner')})),
        lease_expires_at INTEGER CHECK(lease_expires_at IS NULL OR (typeof(lease_expires_at)='integer' AND lease_expires_at>=0)),
        delivered_at INTEGER CHECK(delivered_at IS NULL OR (typeof(delivered_at)='integer' AND delivered_at>=0)),
        PRIMARY KEY(event_id,destination_id),
        CHECK((state='pending' AND lease_owner IS NULL AND lease_expires_at IS NULL AND delivered_at IS NULL) OR
              (state='leased' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL AND delivered_at IS NULL AND attempt>0) OR
              (state='delivered' AND lease_owner IS NULL AND lease_expires_at IS NULL AND delivered_at IS NOT NULL)))""",
    'security_audit_delivery_due': 'CREATE INDEX security_audit_delivery_due ON security_audit_delivery(destination_id,state,next_attempt_at)',
    'security_audit_delivery_scope': """CREATE TRIGGER security_audit_delivery_scope BEFORE UPDATE OF event_id,destination_id ON security_audit_delivery
        BEGIN SELECT RAISE(ABORT,'immutable_audit_delivery_scope'); END""",
    'security_audit_delivery_terminal': """CREATE TRIGGER security_audit_delivery_terminal BEFORE UPDATE ON security_audit_delivery
        WHEN OLD.state='delivered' OR NEW.attempt<OLD.attempt
        BEGIN SELECT RAISE(ABORT,'invalid_audit_delivery_transition'); END""",
    'security_audit_delivery_no_replace': """CREATE TRIGGER security_audit_delivery_no_replace BEFORE INSERT ON security_audit_delivery
        WHEN EXISTS(SELECT 1 FROM security_audit_delivery WHERE event_id=NEW.event_id AND destination_id=NEW.destination_id)
        BEGIN SELECT RAISE(ABORT,'existing_audit_delivery'); END""",
    'security_audit_delivery_no_delete': """CREATE TRIGGER security_audit_delivery_no_delete BEFORE DELETE ON security_audit_delivery
        BEGIN SELECT RAISE(ABORT,'retained_audit_delivery'); END""",
}
MIGRATION_HASH = hashlib.sha256(json.dumps(SCHEMA,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def apply(db):
    journal=db.execute('SELECT version,migration_hash,backup_sha256,applied_at FROM atom_schema_migrations').fetchall()
    db.execute('DROP TABLE atom_schema_migrations')
    for statement in SCHEMA.values():db.execute(statement)
    db.executemany('INSERT INTO atom_schema_migrations VALUES (?,?,?,?)',journal)
