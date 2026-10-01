"""Offline prune evidence and fail-closed guards; no maintenance service is enabled."""
import hashlib
import json

from .audit_recovery_v10 import SCHEMA as V10_SCHEMA
from .audit_archives_v9 import digest, identifier


RECEIPTS = 'security_audit_prune_receipts'
MARKERS = 'security_audit_archived_events'
SCHEMA = {
    'atom_schema_migrations': V10_SCHEMA['atom_schema_migrations'].replace(
        'CHECK(version IN (1,2,3,4,5,6,7,8,9,10))','CHECK(version IN (1,2,3,4,5,6,7,8,9,10,11))'),
    RECEIPTS: f"""CREATE TABLE {RECEIPTS} (
        command_id TEXT PRIMARY KEY NOT NULL CHECK({identifier('command_id')}),
        operator_id TEXT NOT NULL CHECK({identifier('operator_id')}),
        request_sha256 TEXT NOT NULL CHECK({digest('request_sha256')}),
        archive_id TEXT NOT NULL UNIQUE REFERENCES security_audit_archives(archive_id),
        recovery_id TEXT NOT NULL REFERENCES security_audit_isolated_recoveries(recovery_id),
        policy_id TEXT NOT NULL REFERENCES security_audit_retention_policies(policy_id),
        policy_generation INTEGER NOT NULL CHECK(typeof(policy_generation)='integer' AND policy_generation>=1),
        context_sha256 TEXT NOT NULL CHECK({digest('context_sha256')}),
        payload_sha256 TEXT NOT NULL CHECK({digest('payload_sha256')}),
        event_count INTEGER NOT NULL CHECK(typeof(event_count)='integer' AND event_count BETWEEN 1 AND 100),
        occurred_at INTEGER NOT NULL CHECK(typeof(occurred_at)='integer' AND occurred_at>=0))""",
    MARKERS: f"""CREATE TABLE {MARKERS} (
        sequence INTEGER PRIMARY KEY NOT NULL CHECK(sequence>0),
        event_id TEXT NOT NULL UNIQUE CHECK(length(event_id)=32 AND event_id NOT GLOB '*[^0-9a-f]*'),
        scope_kind TEXT NOT NULL CHECK(scope_kind IN ('account','project')),
        scope_id TEXT NOT NULL CHECK({identifier('scope_id')}),
        event_kind TEXT NOT NULL,
        command_id TEXT NOT NULL REFERENCES {RECEIPTS}(command_id))""",
    MARKERS+'_scope': f'CREATE INDEX {MARKERS}_scope ON {MARKERS}(scope_kind,scope_id,sequence)',
    MARKERS+'_command': f'CREATE INDEX {MARKERS}_command ON {MARKERS}(command_id,sequence)',
    RECEIPTS+'_consistent': f"""CREATE TRIGGER {RECEIPTS}_consistent BEFORE INSERT ON {RECEIPTS}
        WHEN atom_prune_authorized(NEW.command_id,'',0) IS NOT 1
        OR NOT EXISTS(SELECT 1 FROM security_audit_archives a
            JOIN security_audit_isolated_recoveries r ON r.archive_id=a.archive_id
            JOIN security_audit_retention_policies p ON p.policy_id=a.policy_id
            WHERE a.archive_id=NEW.archive_id AND r.recovery_id=NEW.recovery_id
            AND p.policy_id=NEW.policy_id AND p.generation=NEW.policy_generation
            AND a.policy_generation=NEW.policy_generation AND p.state='active'
            AND a.context_sha256=NEW.context_sha256 AND a.payload_sha256=NEW.payload_sha256
            AND a.event_count=NEW.event_count AND r.verified_at<=NEW.occurred_at)
        OR EXISTS(SELECT 1 FROM security_audit_retention_holds h WHERE h.policy_id=NEW.policy_id AND h.state='active')
        BEGIN SELECT RAISE(ABORT,'invalid_prune_evidence'); END""",
    MARKERS+'_consistent': f"""CREATE TRIGGER {MARKERS}_consistent BEFORE INSERT ON {MARKERS}
        WHEN atom_prune_authorized(NEW.command_id,NEW.event_id,NEW.sequence) IS NOT 1
        OR NOT EXISTS(SELECT 1 FROM security_audit_events e
            JOIN {RECEIPTS} p ON p.command_id=NEW.command_id
            JOIN security_audit_archives a ON a.archive_id=p.archive_id
            WHERE e.sequence=NEW.sequence AND e.event_id=NEW.event_id
            AND e.scope_kind=NEW.scope_kind AND e.scope_id=NEW.scope_id AND e.event_kind=NEW.event_kind
            AND a.scope_kind=e.scope_kind AND a.scope_id=e.scope_id AND a.event_kind=e.event_kind
            AND e.sequence>a.after_sequence AND e.sequence<=a.upper_sequence
            AND (SELECT count(*) FROM {MARKERS} m WHERE m.command_id=NEW.command_id)<p.event_count)
        BEGIN SELECT RAISE(ABORT,'invalid_archived_marker'); END""",
    'security_audit_no_delete': f"""CREATE TRIGGER security_audit_no_delete BEFORE DELETE ON security_audit_events
        WHEN NOT EXISTS(SELECT 1 FROM {MARKERS} m WHERE m.sequence=OLD.sequence AND m.event_id=OLD.event_id
            AND atom_prune_authorized(m.command_id,OLD.event_id,OLD.sequence)=1)
        OR EXISTS(SELECT 1 FROM security_audit_delivery d WHERE d.event_id=OLD.event_id)
        BEGIN SELECT RAISE(ABORT,'immutable_audit_event'); END""",
    'security_audit_delivery_no_delete': f"""CREATE TRIGGER security_audit_delivery_no_delete BEFORE DELETE ON security_audit_delivery
        WHEN OLD.state<>'delivered' OR NOT EXISTS(SELECT 1 FROM {MARKERS} m
            JOIN security_audit_events e ON e.sequence=m.sequence AND e.event_id=m.event_id
            WHERE m.event_id=OLD.event_id AND atom_prune_authorized(m.command_id,m.event_id,m.sequence)=1)
        BEGIN SELECT RAISE(ABORT,'retained_audit_delivery'); END""",
    'security_audit_no_archived_reuse': f"""CREATE TRIGGER security_audit_no_archived_reuse BEFORE INSERT ON security_audit_events
        WHEN EXISTS(SELECT 1 FROM {MARKERS} m WHERE m.sequence=NEW.sequence OR m.event_id=NEW.event_id)
        BEGIN SELECT RAISE(ABORT,'archived_audit_identity'); END""",
}
for table,key,alternate in ((RECEIPTS,'command_id','archive_id'),(MARKERS,'sequence','event_id')):
    for action in ('UPDATE','DELETE'):
        name=table+'_no_'+action.lower()
        SCHEMA[name]=f"""CREATE TRIGGER {name} BEFORE {action} ON {table}
            BEGIN SELECT RAISE(ABORT,'immutable_prune_evidence'); END"""
    name=table+'_no_replace'
    SCHEMA[name]=f"""CREATE TRIGGER {name} BEFORE INSERT ON {table}
        WHEN EXISTS(SELECT 1 FROM {table} WHERE {key}=NEW.{key} OR {alternate}=NEW.{alternate})
        BEGIN SELECT RAISE(ABORT,'existing_prune_evidence'); END"""

MIGRATION_HASH=hashlib.sha256(json.dumps(SCHEMA,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def apply(db):
    journal=db.execute('SELECT version,migration_hash,backup_sha256,applied_at FROM atom_schema_migrations').fetchall()
    db.execute('DROP TABLE atom_schema_migrations')
    db.execute('DROP TRIGGER security_audit_no_delete')
    db.execute('DROP TRIGGER security_audit_delivery_no_delete')
    for statement in SCHEMA.values():
        db.execute(statement)
    db.executemany('INSERT INTO atom_schema_migrations VALUES (?,?,?,?)',journal)
