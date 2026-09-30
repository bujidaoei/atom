"""Additive release identities; application routing is not enabled by DDL."""
import hashlib
import json

from .revision_v1 import HASH_CHECK, SCHEMA as V1

JOURNAL = V1['atom_schema_migrations'].replace('CHECK(version=1)', 'CHECK(version IN (1,2))')
SCHEMA = {
    'atom_schema_migrations': JOURNAL,
    'verification_requests': """CREATE TABLE verification_requests (
        id TEXT NOT NULL PRIMARY KEY, workspace_id TEXT NOT NULL, project_id TEXT NOT NULL,
        revision_id TEXT NOT NULL, contract_digest TEXT NOT NULL CHECK(%s),
        contract_json TEXT NOT NULL CHECK(json_valid(contract_json) AND length(contract_json)<=1048576),
        policy_digest TEXT NOT NULL CHECK(%s), runner_version TEXT NOT NULL CHECK(length(runner_version) BETWEEN 1 AND 128),
        initiator_id TEXT NOT NULL REFERENCES users(id), created_at INTEGER NOT NULL,
        deadline INTEGER NOT NULL CHECK(typeof(deadline)='integer' AND deadline>created_at),
        UNIQUE(id,workspace_id,revision_id,contract_digest,policy_digest),
        FOREIGN KEY(workspace_id,project_id) REFERENCES revision_workspaces(id,project_id),
        FOREIGN KEY(revision_id,workspace_id) REFERENCES revision_records(id,workspace_id))""" % (
            HASH_CHECK.format('contract_digest'), HASH_CHECK.format('policy_digest')),
    'verification_results': """CREATE TABLE verification_results (
        request_id TEXT NOT NULL PRIMARY KEY, workspace_id TEXT NOT NULL, revision_id TEXT NOT NULL,
        contract_digest TEXT NOT NULL, policy_digest TEXT NOT NULL,
        outcome TEXT NOT NULL CHECK(outcome IN ('passed','failed','cancelled','timed_out')),
        total INTEGER NOT NULL CHECK(typeof(total)='integer' AND total>0),
        passed INTEGER NOT NULL CHECK(typeof(passed)='integer' AND passed>=0 AND passed<=total),
        report_json TEXT NOT NULL CHECK(json_valid(report_json) AND length(report_json)<=1048576),
        completed_at INTEGER NOT NULL,
        CHECK(outcome!='passed' OR passed=total),
        UNIQUE(request_id,workspace_id,revision_id,contract_digest,policy_digest),
        FOREIGN KEY(request_id,workspace_id,revision_id,contract_digest,policy_digest)
        REFERENCES verification_requests(id,workspace_id,revision_id,contract_digest,policy_digest))""",
    'release_records': """CREATE TABLE release_records (
        id TEXT NOT NULL PRIMARY KEY, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
        revision_id TEXT NOT NULL, verification_id TEXT NOT NULL,
        contract_digest TEXT NOT NULL, policy_digest TEXT NOT NULL,
        audience TEXT NOT NULL CHECK(audience IN ('owner','public')),
        creator_id TEXT NOT NULL REFERENCES users(id), previous_release_id TEXT,
        created_at INTEGER NOT NULL, UNIQUE(id,project_id),
        FOREIGN KEY(workspace_id,project_id) REFERENCES revision_workspaces(id,project_id),
        FOREIGN KEY(verification_id,workspace_id,revision_id,contract_digest,policy_digest)
        REFERENCES verification_results(request_id,workspace_id,revision_id,contract_digest,policy_digest),
        FOREIGN KEY(previous_release_id,project_id) REFERENCES release_records(id,project_id))""",
    'release_publications': """CREATE TABLE release_publications (
        project_id TEXT NOT NULL PRIMARY KEY REFERENCES projects(id), slug TEXT NOT NULL UNIQUE,
        release_id TEXT NOT NULL, generation INTEGER NOT NULL CHECK(typeof(generation)='integer' AND generation>0),
        live INTEGER NOT NULL CHECK(live IN (0,1)),
        FOREIGN KEY(release_id,project_id) REFERENCES release_records(id,project_id))""",
    'release_requires_passing_evidence': """CREATE TRIGGER release_requires_passing_evidence BEFORE INSERT ON release_records
        WHEN NOT EXISTS (SELECT 1 FROM verification_results WHERE request_id=NEW.verification_id AND outcome='passed')
        BEGIN SELECT RAISE(ABORT,'release_requires_passing_evidence'); END""",
    'verification_result_time': """CREATE TRIGGER verification_result_time BEFORE INSERT ON verification_results
        WHEN NOT EXISTS (SELECT 1 FROM verification_requests WHERE id=NEW.request_id AND
        NEW.completed_at>=created_at AND (NEW.outcome!='passed' OR NEW.completed_at<=deadline))
        BEGIN SELECT RAISE(ABORT,'verification_result_time'); END""",
}
for table in ('verification_requests', 'verification_results', 'release_records'):
    for operation in ('UPDATE', 'DELETE'):
        name = table + '_no_' + operation.lower()
        SCHEMA[name] = f"CREATE TRIGGER {name} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_release_evidence'); END"

MIGRATION_HASH = hashlib.sha256(json.dumps(SCHEMA, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def apply(db):
    # No foreign keys target the migration journal. Preserve the original row.
    journal = db.execute('SELECT version,migration_hash,backup_sha256,applied_at FROM atom_schema_migrations').fetchall()
    db.execute('DROP TABLE atom_schema_migrations')
    for statement in SCHEMA.values():
        db.execute(statement)
    db.executemany('INSERT INTO atom_schema_migrations VALUES (?,?,?,?)', journal)
