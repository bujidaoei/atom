"""Offline adoption provenance; no serving or adoption API is enabled."""
import hashlib
import json

from .audit_pruning_v11 import SCHEMA as V11
from .revision_v1 import HASH_CHECK, SCHEMA as V1


RECORDS = """CREATE TABLE "revision_records" (
        id TEXT NOT NULL PRIMARY KEY, workspace_id TEXT NOT NULL, project_id TEXT NOT NULL,
        parent_revision_id TEXT, artifact_key TEXT NOT NULL, snapshot_revision TEXT NOT NULL,
        producing_attempt_id TEXT UNIQUE, created_at INTEGER NOT NULL, adoption_id TEXT UNIQUE,
        CHECK((parent_revision_id IS NULL AND producing_attempt_id IS NULL AND adoption_id IS NULL) OR
              (parent_revision_id IS NOT NULL AND producing_attempt_id IS NOT NULL AND adoption_id IS NULL) OR
              (parent_revision_id IS NOT NULL AND producing_attempt_id IS NULL AND adoption_id IS NOT NULL)),
        UNIQUE(id,workspace_id), UNIQUE(id,producing_attempt_id,workspace_id),
        FOREIGN KEY(workspace_id,project_id) REFERENCES revision_workspaces(id,project_id),
        FOREIGN KEY(parent_revision_id,workspace_id) REFERENCES revision_records(id,workspace_id),
        FOREIGN KEY(producing_attempt_id,workspace_id) REFERENCES revision_attempts(id,workspace_id),
        FOREIGN KEY(adoption_id) REFERENCES revision_adoptions(id),
        FOREIGN KEY(artifact_key,snapshot_revision) REFERENCES revision_artifacts(key,revision))"""

SCHEMA = {
    'atom_schema_migrations': V11['atom_schema_migrations'].replace(
        'CHECK(version IN (1,2,3,4,5,6,7,8,9,10,11))',
        'CHECK(version IN (1,2,3,4,5,6,7,8,9,10,11,12))'),
    'revision_records': RECORDS,
    'revision_adoptions': """CREATE TABLE revision_adoptions (
        id TEXT NOT NULL PRIMARY KEY CHECK(length(id) BETWEEN 1 AND 128),
        project_id TEXT NOT NULL REFERENCES projects(id),
        source_heat_id TEXT NOT NULL REFERENCES race_heats(id),
        source_workspace_id TEXT NOT NULL, source_revision_id TEXT NOT NULL,
        target_workspace_id TEXT NOT NULL, expected_parent_revision_id TEXT NOT NULL,
        actor_id TEXT NOT NULL REFERENCES users(id),
        request_hash TEXT NOT NULL CHECK(%s), created_at INTEGER NOT NULL,
        FOREIGN KEY(source_workspace_id,project_id) REFERENCES revision_workspaces(id,project_id),
        FOREIGN KEY(target_workspace_id,project_id) REFERENCES revision_workspaces(id,project_id),
        FOREIGN KEY(source_revision_id,source_workspace_id) REFERENCES revision_records(id,workspace_id),
        FOREIGN KEY(expected_parent_revision_id,target_workspace_id) REFERENCES revision_records(id,workspace_id))""" % HASH_CHECK.format('request_hash'),
    'revision_adoptions_no_update': """CREATE TRIGGER revision_adoptions_no_update BEFORE UPDATE ON revision_adoptions
        BEGIN SELECT RAISE(ABORT,'immutable_adoption_evidence'); END""",
    'revision_adoptions_no_delete': """CREATE TRIGGER revision_adoptions_no_delete BEFORE DELETE ON revision_adoptions
        BEGIN SELECT RAISE(ABORT,'immutable_adoption_evidence'); END""",
    'revision_adoption_scope': """CREATE TRIGGER revision_adoption_scope BEFORE INSERT ON revision_adoptions
        WHEN NOT EXISTS (SELECT 1 FROM revision_workspaces source
          JOIN revision_workspaces target ON target.id=NEW.target_workspace_id
          JOIN race_heats heat ON heat.id=NEW.source_heat_id
          JOIN races race ON race.id=heat.race_id
          JOIN projects project ON project.id=NEW.project_id
          WHERE source.id=NEW.source_workspace_id AND source.project_id=NEW.project_id
          AND source.heat_id=heat.id AND source.current_revision_id=NEW.source_revision_id
          AND heat.status='done' AND race.project_id=NEW.project_id
          AND target.project_id=NEW.project_id AND target.heat_id IS NULL
          AND target.current_revision_id=NEW.expected_parent_revision_id
          AND target.active_attempt_id IS NULL AND project.active_run_id IS NULL
          AND project.user_id=NEW.actor_id)
        BEGIN SELECT RAISE(ABORT,'invalid_adoption_scope'); END""",
    'revision_adoption_record': """CREATE TRIGGER revision_adoption_record BEFORE INSERT ON revision_records
        WHEN NEW.adoption_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM revision_adoptions adoption
          JOIN revision_records source ON source.id=adoption.source_revision_id
            AND source.workspace_id=adoption.source_workspace_id
          JOIN revision_workspaces target ON target.id=adoption.target_workspace_id
          WHERE adoption.id=NEW.adoption_id AND adoption.project_id=NEW.project_id
            AND adoption.target_workspace_id=NEW.workspace_id
            AND adoption.expected_parent_revision_id=NEW.parent_revision_id
            AND target.current_revision_id=NEW.parent_revision_id
            AND target.active_attempt_id IS NULL
            AND source.artifact_key=NEW.artifact_key
            AND source.snapshot_revision=NEW.snapshot_revision)
        BEGIN SELECT RAISE(ABORT,'invalid_adoption_revision'); END""",
}

MIGRATION_HASH = hashlib.sha256(json.dumps(SCHEMA, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def apply(db):
    journal = db.execute('SELECT version,migration_hash,backup_sha256,applied_at FROM atom_schema_migrations').fetchall()
    db.execute('DROP TABLE atom_schema_migrations')
    db.execute(SCHEMA['atom_schema_migrations'])
    db.executemany('INSERT INTO atom_schema_migrations VALUES (?,?,?,?)', journal)
    db.execute(SCHEMA['revision_adoptions'])
    db.execute(RECORDS.replace('CREATE TABLE "revision_records"', 'CREATE TABLE revision_records_next', 1))
    db.execute('''INSERT INTO revision_records_next
        (id,workspace_id,project_id,parent_revision_id,artifact_key,snapshot_revision,
         producing_attempt_id,created_at,adoption_id)
        SELECT id,workspace_id,project_id,parent_revision_id,artifact_key,snapshot_revision,
               producing_attempt_id,created_at,NULL FROM revision_records''')
    db.execute('DROP TABLE revision_records')
    db.execute('ALTER TABLE revision_records_next RENAME TO revision_records')
    db.execute(V1['revision_one_root'])
    for name in ('revision_records_no_update', 'revision_records_no_delete'):
        db.execute(V1[name])
    for name in ('revision_adoptions_no_update', 'revision_adoptions_no_delete',
                 'revision_adoption_scope', 'revision_adoption_record'):
        db.execute(SCHEMA[name])
