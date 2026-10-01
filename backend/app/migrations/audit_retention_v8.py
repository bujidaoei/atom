"""Explicit retention policy/hold authority; no archive or deletion permission."""
import hashlib
import json

from .audit_commands_v7 import SCHEMA as V7_SCHEMA


def identifier(column, maximum=100):
    return f"length({column}) BETWEEN 1 AND {maximum} AND {column} NOT GLOB '*[^A-Za-z0-9_.-]*'"


SCHEMA = {
    'atom_schema_migrations': V7_SCHEMA['atom_schema_migrations'].replace(
        'CHECK(version IN (1,2,3,4,5,6,7))', 'CHECK(version IN (1,2,3,4,5,6,7,8))'),
    'security_audit_retention_policies': f"""CREATE TABLE security_audit_retention_policies (
        policy_id TEXT PRIMARY KEY NOT NULL CHECK({identifier('policy_id')}),
        scope_kind TEXT NOT NULL CHECK(scope_kind IN ('account','project')),
        scope_id TEXT NOT NULL CHECK({identifier('scope_id')}),
        event_kind TEXT NOT NULL CHECK(event_kind IN ('console.session.created','console.session.revoked',
            'console.account_sessions.revoked','content.handoff.issued','content.session.created','release.published','release.unpublished')),
        generation INTEGER NOT NULL CHECK(typeof(generation)='integer' AND generation>=1),
        state TEXT NOT NULL CHECK(state IN ('active','paused')),
        min_age_seconds INTEGER NOT NULL CHECK(typeof(min_age_seconds)='integer' AND min_age_seconds>=1),
        archive_store_id TEXT NOT NULL CHECK({identifier('archive_store_id',64)}),
        created_at INTEGER NOT NULL CHECK(typeof(created_at)='integer' AND created_at>=0),
        updated_at INTEGER NOT NULL CHECK(typeof(updated_at)='integer' AND updated_at>=created_at),
        UNIQUE(scope_kind,scope_id,event_kind),
        CHECK((scope_kind='account' AND event_kind IN ('console.session.created','console.session.revoked','console.account_sessions.revoked')) OR
              (scope_kind='project' AND event_kind IN ('content.handoff.issued','content.session.created','release.published','release.unpublished'))))""",
    'security_audit_retention_holds': f"""CREATE TABLE security_audit_retention_holds (
        hold_id TEXT PRIMARY KEY NOT NULL CHECK({identifier('hold_id')}),
        policy_id TEXT NOT NULL REFERENCES security_audit_retention_policies(policy_id),
        kind TEXT NOT NULL CHECK(kind IN ('legal','operational')),
        state TEXT NOT NULL CHECK(state IN ('active','released')),
        policy_generation INTEGER NOT NULL CHECK(typeof(policy_generation)='integer' AND policy_generation>=1),
        created_at INTEGER NOT NULL CHECK(typeof(created_at)='integer' AND created_at>=0),
        updated_at INTEGER NOT NULL CHECK(typeof(updated_at)='integer' AND updated_at>=created_at),
        UNIQUE(policy_id,policy_generation))""",
    'security_audit_retention_holds_policy': 'CREATE INDEX security_audit_retention_holds_policy ON security_audit_retention_holds(policy_id,state,hold_id)',
    'security_audit_retention_commands': f"""CREATE TABLE security_audit_retention_commands (
        command_id TEXT PRIMARY KEY NOT NULL CHECK({identifier('command_id')}),
        policy_id TEXT NOT NULL REFERENCES security_audit_retention_policies(policy_id),
        operator_id TEXT NOT NULL CHECK({identifier('operator_id')}),
        action TEXT NOT NULL CHECK(action IN ('create_policy','update_policy','place_hold','release_hold')),
        request_sha256 TEXT NOT NULL CHECK(length(request_sha256)=64 AND request_sha256 NOT GLOB '*[^0-9a-f]*'),
        expected_generation INTEGER NOT NULL CHECK(typeof(expected_generation)='integer' AND expected_generation>=0),
        generation INTEGER NOT NULL CHECK(typeof(generation)='integer' AND generation=expected_generation+1),
        state TEXT NOT NULL CHECK(state IN ('active','paused')),
        min_age_seconds INTEGER NOT NULL CHECK(typeof(min_age_seconds)='integer' AND min_age_seconds>=1),
        archive_store_id TEXT NOT NULL CHECK({identifier('archive_store_id',64)}),
        hold_id TEXT REFERENCES security_audit_retention_holds(hold_id),
        hold_kind TEXT CHECK(hold_kind IS NULL OR hold_kind IN ('legal','operational')),
        hold_state TEXT CHECK(hold_state IS NULL OR hold_state IN ('active','released')),
        occurred_at INTEGER NOT NULL CHECK(typeof(occurred_at)='integer' AND occurred_at>=0),
        UNIQUE(policy_id,generation),
        CHECK((action='create_policy' AND expected_generation=0) OR (action<>'create_policy' AND expected_generation>=1)),
        CHECK((action IN ('create_policy','update_policy') AND hold_id IS NULL AND hold_kind IS NULL AND hold_state IS NULL) OR
              (action='place_hold' AND hold_id IS NOT NULL AND hold_kind IS NOT NULL AND hold_state IS NOT NULL AND hold_state='active') OR
              (action='release_hold' AND hold_id IS NOT NULL AND hold_kind IS NOT NULL AND hold_state IS NOT NULL AND hold_state='released')))""",
    'security_audit_retention_policies_identity': """CREATE TRIGGER security_audit_retention_policies_identity BEFORE UPDATE OF policy_id,scope_kind,scope_id,event_kind,created_at ON security_audit_retention_policies
        BEGIN SELECT RAISE(ABORT,'immutable_retention_identity'); END""",
    'security_audit_retention_policies_generation': """CREATE TRIGGER security_audit_retention_policies_generation BEFORE UPDATE ON security_audit_retention_policies
        WHEN NEW.generation<>OLD.generation+1 OR NEW.updated_at<OLD.updated_at
        BEGIN SELECT RAISE(ABORT,'invalid_retention_generation'); END""",
    'security_audit_retention_holds_identity': """CREATE TRIGGER security_audit_retention_holds_identity BEFORE UPDATE OF hold_id,policy_id,kind,created_at ON security_audit_retention_holds
        BEGIN SELECT RAISE(ABORT,'immutable_retention_hold'); END""",
    'security_audit_retention_holds_transition': """CREATE TRIGGER security_audit_retention_holds_transition BEFORE UPDATE ON security_audit_retention_holds
        WHEN OLD.state<>'active' OR NEW.state<>'released' OR NEW.policy_generation<=OLD.policy_generation OR NEW.updated_at<OLD.updated_at
        BEGIN SELECT RAISE(ABORT,'invalid_retention_hold_transition'); END""",
    'security_audit_retention_holds_insert': """CREATE TRIGGER security_audit_retention_holds_insert BEFORE INSERT ON security_audit_retention_holds
        WHEN NEW.state<>'active' OR NEW.created_at<>NEW.updated_at
        OR EXISTS(SELECT 1 FROM security_audit_retention_commands c WHERE c.policy_id=NEW.policy_id AND c.generation=NEW.policy_generation)
        OR NOT EXISTS(SELECT 1 FROM security_audit_retention_policies p
            WHERE p.policy_id=NEW.policy_id AND p.generation=NEW.policy_generation AND p.updated_at=NEW.updated_at)
        BEGIN SELECT RAISE(ABORT,'inconsistent_retention_hold'); END""",
    'security_audit_retention_holds_update': """CREATE TRIGGER security_audit_retention_holds_update BEFORE UPDATE ON security_audit_retention_holds
        WHEN EXISTS(SELECT 1 FROM security_audit_retention_commands c WHERE c.policy_id=NEW.policy_id AND c.generation=NEW.policy_generation)
        OR NOT EXISTS(SELECT 1 FROM security_audit_retention_policies p
            WHERE p.policy_id=NEW.policy_id AND p.generation=NEW.policy_generation AND p.updated_at=NEW.updated_at)
        BEGIN SELECT RAISE(ABORT,'inconsistent_retention_hold'); END""",
    'security_audit_retention_commands_no_update': """CREATE TRIGGER security_audit_retention_commands_no_update BEFORE UPDATE ON security_audit_retention_commands
        BEGIN SELECT RAISE(ABORT,'immutable_retention_command'); END""",
    'security_audit_retention_commands_consistent': """CREATE TRIGGER security_audit_retention_commands_consistent BEFORE INSERT ON security_audit_retention_commands
        WHEN NOT EXISTS(SELECT 1 FROM security_audit_retention_policies p WHERE p.policy_id=NEW.policy_id
            AND p.generation=NEW.generation AND p.state=NEW.state AND p.min_age_seconds=NEW.min_age_seconds
            AND p.archive_store_id=NEW.archive_store_id AND p.updated_at=NEW.occurred_at)
        OR (NEW.hold_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM security_audit_retention_holds h
            WHERE h.hold_id=NEW.hold_id AND h.policy_id=NEW.policy_id AND h.kind=NEW.hold_kind AND h.state=NEW.hold_state
            AND h.policy_generation=NEW.generation AND h.updated_at=NEW.occurred_at))
        BEGIN SELECT RAISE(ABORT,'inconsistent_retention_command'); END""",
}
for table, key in (('security_audit_retention_policies', 'policy_id'),
                   ('security_audit_retention_holds', 'hold_id'),
                   ('security_audit_retention_commands', 'command_id')):
    SCHEMA[table+'_no_delete'] = f"""CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table}
        BEGIN SELECT RAISE(ABORT,'retained_retention_authority'); END"""
    collision = f'{key}=NEW.{key}'
    if table == 'security_audit_retention_policies':
        collision += ' OR (scope_kind=NEW.scope_kind AND scope_id=NEW.scope_id AND event_kind=NEW.event_kind)'
    if table == 'security_audit_retention_commands':
        collision += ' OR (policy_id=NEW.policy_id AND generation=NEW.generation)'
    SCHEMA[table+'_no_replace'] = f"""CREATE TRIGGER {table}_no_replace BEFORE INSERT ON {table}
        WHEN EXISTS(SELECT 1 FROM {table} WHERE {collision})
        BEGIN SELECT RAISE(ABORT,'existing_retention_authority'); END"""

MIGRATION_HASH = hashlib.sha256(json.dumps(SCHEMA, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def apply(db):
    journal = db.execute('SELECT version,migration_hash,backup_sha256,applied_at FROM atom_schema_migrations').fetchall()
    db.execute('DROP TABLE atom_schema_migrations')
    for statement in SCHEMA.values():
        db.execute(statement)
    db.executemany('INSERT INTO atom_schema_migrations VALUES (?,?,?,?)', journal)
