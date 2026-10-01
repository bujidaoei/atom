"""Immutable operator command evidence for destination lifecycle transitions."""
import hashlib
import json

from .audit_governance_v6 import SCHEMA as V6_SCHEMA


SCHEMA = {
    'atom_schema_migrations': V6_SCHEMA['atom_schema_migrations'].replace(
        'CHECK(version IN (1,2,3,4,5,6))', 'CHECK(version IN (1,2,3,4,5,6,7))'),
    'security_audit_destination_commands': """CREATE TABLE security_audit_destination_commands (
        command_id TEXT PRIMARY KEY NOT NULL CHECK(length(command_id) BETWEEN 1 AND 100 AND command_id NOT GLOB '*[^A-Za-z0-9_.-]*'),
        destination_id TEXT NOT NULL REFERENCES security_audit_destinations(destination_id),
        operator_id TEXT NOT NULL CHECK(length(operator_id) BETWEEN 1 AND 100 AND operator_id NOT GLOB '*[^A-Za-z0-9_.-]*'),
        action TEXT NOT NULL CHECK(action IN ('register','suspend','resume','block','retire')),
        expected_generation INTEGER NOT NULL CHECK(typeof(expected_generation)='integer' AND expected_generation>=0),
        generation INTEGER NOT NULL CHECK(typeof(generation)='integer' AND generation=expected_generation+1),
        state TEXT NOT NULL CHECK(state IN ('active','paused','blocked','retired')),
        occurred_at INTEGER NOT NULL CHECK(typeof(occurred_at)='integer' AND occurred_at>=0),
        reason TEXT CHECK(reason IS NULL OR reason IN ('receiver_configuration','invalid_payload')),
        required_through_sequence INTEGER CHECK(required_through_sequence IS NULL OR (typeof(required_through_sequence)='integer' AND required_through_sequence>=0)),
        UNIQUE(destination_id,generation),
        CHECK((action='register' AND expected_generation=0 AND state='active') OR
              (action='resume' AND expected_generation>=1 AND state='active') OR
              (action='suspend' AND expected_generation>=1 AND state='paused') OR
              (action='block' AND expected_generation>=1 AND state='blocked') OR
              (action='retire' AND expected_generation>=1 AND state='retired')),
        CHECK((action='block' AND reason IS NOT NULL) OR (action<>'block' AND reason IS NULL)),
        CHECK((action='retire' AND required_through_sequence IS NOT NULL) OR
              (action<>'retire' AND required_through_sequence IS NULL)))""",
    'security_audit_destination_commands_no_update': """CREATE TRIGGER security_audit_destination_commands_no_update BEFORE UPDATE ON security_audit_destination_commands
        BEGIN SELECT RAISE(ABORT,'immutable_audit_command'); END""",
    'security_audit_destination_commands_no_delete': """CREATE TRIGGER security_audit_destination_commands_no_delete BEFORE DELETE ON security_audit_destination_commands
        BEGIN SELECT RAISE(ABORT,'retained_audit_command'); END""",
    'security_audit_destination_commands_no_replace': """CREATE TRIGGER security_audit_destination_commands_no_replace BEFORE INSERT ON security_audit_destination_commands
        WHEN EXISTS(SELECT 1 FROM security_audit_destination_commands WHERE command_id=NEW.command_id OR (destination_id=NEW.destination_id AND generation=NEW.generation))
        BEGIN SELECT RAISE(ABORT,'existing_audit_command'); END""",
    'security_audit_destination_commands_consistent': """CREATE TRIGGER security_audit_destination_commands_consistent BEFORE INSERT ON security_audit_destination_commands
        WHEN NOT EXISTS(SELECT 1 FROM security_audit_destinations r WHERE r.destination_id=NEW.destination_id
            AND r.generation=NEW.generation AND r.state=NEW.state AND r.updated_at=NEW.occurred_at
            AND r.blocked_reason IS NEW.reason AND r.required_through_sequence IS NEW.required_through_sequence)
        BEGIN SELECT RAISE(ABORT,'inconsistent_audit_command'); END""",
}
MIGRATION_HASH = hashlib.sha256(json.dumps(SCHEMA, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def apply(db):
    journal = db.execute('SELECT version,migration_hash,backup_sha256,applied_at FROM atom_schema_migrations').fetchall()
    db.execute('DROP TABLE atom_schema_migrations')
    for statement in SCHEMA.values():
        db.execute(statement)
    db.executemany('INSERT INTO atom_schema_migrations VALUES (?,?,?,?)', journal)
