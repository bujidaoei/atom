"""Offline, first-class provenance for an immutable verified release rollback."""
import hashlib
import json

from .verifier_v13 import SCHEMA as V13
from .audit_v5 import identity
from .audit_retention_v8 import identifier


TABLE = 'release_rollback_sources'

SCHEMA = {
    'atom_schema_migrations': V13['atom_schema_migrations'].replace(
        'CHECK(version IN (1,2,3,4,5,6,7,8,9,10,11,12,13))',
        'CHECK(version IN (1,2,3,4,5,6,7,8,9,10,11,12,13,14))'),
    TABLE: f"""CREATE TABLE {TABLE} (
        new_release_id TEXT NOT NULL PRIMARY KEY CHECK({identity('new_release_id')}),
        project_id TEXT NOT NULL CHECK({identifier('project_id')}),
        source_release_id TEXT NOT NULL CHECK({identifier('source_release_id')}),
        displaced_release_id TEXT NOT NULL CHECK({identifier('displaced_release_id')}),
        command_id TEXT NOT NULL UNIQUE CHECK({identity('command_id')}),
        generation INTEGER NOT NULL CHECK(typeof(generation)='integer' AND generation>1),
        created_at INTEGER NOT NULL CHECK(typeof(created_at)='integer' AND created_at>=0),
        CHECK(new_release_id<>source_release_id AND new_release_id<>displaced_release_id
              AND source_release_id<>displaced_release_id),
        FOREIGN KEY(new_release_id,project_id) REFERENCES release_records(id,project_id),
        FOREIGN KEY(source_release_id,project_id) REFERENCES release_records(id,project_id),
        FOREIGN KEY(displaced_release_id,project_id) REFERENCES release_records(id,project_id))""",
    TABLE+'_scope': f"""CREATE TRIGGER {TABLE}_scope BEFORE INSERT ON {TABLE}
        WHEN NOT EXISTS (SELECT 1 FROM release_records n
          JOIN release_records s ON s.id=NEW.source_release_id AND s.project_id=n.project_id
          JOIN verification_attestations t ON t.request_id=s.verification_id
          JOIN release_publications p ON p.project_id=n.project_id
          JOIN command_receipts c ON c.project_id=n.project_id AND c.key='rollback:'||NEW.command_id
          JOIN security_audit_events a ON a.scope_kind='project' AND a.scope_id=n.project_id
              AND a.event_kind='release.published' AND a.release_id=n.id
              AND a.operation_id=n.id AND a.publication_generation=NEW.generation
          WHERE n.id=NEW.new_release_id AND n.project_id=NEW.project_id
          AND n.previous_release_id=NEW.displaced_release_id
          AND (n.workspace_id,n.revision_id,n.verification_id,n.contract_digest,
               n.policy_digest,n.audience)=(s.workspace_id,s.revision_id,s.verification_id,
               s.contract_digest,s.policy_digest,s.audience)
          AND p.release_id=n.id AND p.generation=NEW.generation AND p.live=1
          AND length(c.digest)=64 AND json_valid(c.response_json)
          AND json_extract(c.response_json,'$.release_id')=n.id
          AND json_extract(c.response_json,'$.source_release_id')=s.id
          AND json_extract(c.response_json,'$.displaced_release_id')=NEW.displaced_release_id
          AND json_extract(c.response_json,'$.generation')=NEW.generation
          AND json_extract(c.response_json,'$.slug')=p.slug)
        BEGIN SELECT RAISE(ABORT,'invalid_release_rollback_source'); END""",
}
for action in ('UPDATE', 'DELETE'):
    name = TABLE + '_no_' + action.lower()
    SCHEMA[name] = f"""CREATE TRIGGER {name} BEFORE {action} ON {TABLE}
        BEGIN SELECT RAISE(ABORT,'immutable_release_rollback_source'); END"""

MIGRATION_HASH = hashlib.sha256(json.dumps(SCHEMA, sort_keys=True,
                                           separators=(',', ':')).encode()).hexdigest()


def apply(db):
    journal = db.execute('SELECT version,migration_hash,backup_sha256,applied_at '
                         'FROM atom_schema_migrations').fetchall()
    db.execute('DROP TABLE atom_schema_migrations')
    for statement in SCHEMA.values():
        db.execute(statement)
    db.executemany('INSERT INTO atom_schema_migrations VALUES (?,?,?,?)', journal)
