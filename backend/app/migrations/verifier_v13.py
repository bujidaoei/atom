"""Offline verifier provenance schema; no worker or serving admission."""
import hashlib
import json

from .adoption_v12 import SCHEMA as V12
from .audit_archives_v9 import digest, identifier


DISPATCH = 'verification_dispatches'
ATTESTATION = 'verification_attestations'
ROUTE = "length(route_id)=32 AND route_id NOT GLOB '*[^0-9a-f]*'"

SCHEMA = {
    'atom_schema_migrations': V12['atom_schema_migrations'].replace(
        'CHECK(version IN (1,2,3,4,5,6,7,8,9,10,11,12))',
        'CHECK(version IN (1,2,3,4,5,6,7,8,9,10,11,12,13))'),
    DISPATCH: f"""CREATE TABLE {DISPATCH} (
        request_id TEXT NOT NULL PRIMARY KEY,
        project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, revision_id TEXT NOT NULL,
        contract_digest TEXT NOT NULL CHECK({digest('contract_digest')}),
        policy_digest TEXT NOT NULL CHECK({digest('policy_digest')}),
        runner_version TEXT NOT NULL CHECK({identifier('runner_version',128)}),
        artifact_key TEXT NOT NULL CHECK({digest('artifact_key')}),
        snapshot_revision TEXT NOT NULL CHECK({digest('snapshot_revision')}),
        artifact_size INTEGER NOT NULL CHECK(typeof(artifact_size)='integer' AND artifact_size BETWEEN 14 AND 68157454),
        route_id TEXT NOT NULL UNIQUE CHECK({ROUTE}),
        verifier_id TEXT NOT NULL CHECK({identifier('verifier_id')}),
        environment_digest TEXT NOT NULL CHECK({digest('environment_digest')}),
        credential_digest TEXT NOT NULL CHECK({digest('credential_digest')}),
        issued_at INTEGER NOT NULL CHECK(typeof(issued_at)='integer' AND issued_at>=0),
        deadline INTEGER NOT NULL CHECK(typeof(deadline)='integer' AND deadline>issued_at),
        UNIQUE(request_id,verifier_id,environment_digest,artifact_key,snapshot_revision),
        FOREIGN KEY(request_id,workspace_id,revision_id,contract_digest,policy_digest)
          REFERENCES verification_requests(id,workspace_id,revision_id,contract_digest,policy_digest),
        FOREIGN KEY(artifact_key,snapshot_revision) REFERENCES revision_artifacts(key,revision))""",
    ATTESTATION: f"""CREATE TABLE {ATTESTATION} (
        request_id TEXT NOT NULL PRIMARY KEY REFERENCES verification_results(request_id),
        verifier_id TEXT NOT NULL CHECK({identifier('verifier_id')}),
        environment_digest TEXT NOT NULL CHECK({digest('environment_digest')}),
        artifact_key TEXT NOT NULL CHECK({digest('artifact_key')}),
        snapshot_revision TEXT NOT NULL CHECK({digest('snapshot_revision')}),
        report_digest TEXT NOT NULL CHECK({digest('report_digest')}),
        observed_at INTEGER NOT NULL CHECK(typeof(observed_at)='integer' AND observed_at>=0),
        FOREIGN KEY(request_id,verifier_id,environment_digest,artifact_key,snapshot_revision)
          REFERENCES verification_dispatches(request_id,verifier_id,environment_digest,artifact_key,snapshot_revision))""",
    DISPATCH+'_scope': f"""CREATE TRIGGER {DISPATCH}_scope BEFORE INSERT ON {DISPATCH}
        WHEN NOT EXISTS (SELECT 1 FROM verification_requests q
          JOIN revision_records r ON r.id=q.revision_id AND r.workspace_id=q.workspace_id
          JOIN revision_artifacts a ON a.key=r.artifact_key AND a.revision=r.snapshot_revision
          JOIN revision_workspaces w ON w.id=q.workspace_id AND w.project_id=q.project_id
          JOIN projects p ON p.id=q.project_id
          WHERE q.id=NEW.request_id AND q.project_id=NEW.project_id
          AND q.workspace_id=NEW.workspace_id AND q.revision_id=NEW.revision_id
          AND q.contract_digest=NEW.contract_digest AND q.policy_digest=NEW.policy_digest
          AND q.runner_version=NEW.runner_version AND r.project_id=NEW.project_id
          AND a.key=NEW.artifact_key AND a.revision=NEW.snapshot_revision
          AND a.size=NEW.artifact_size AND w.current_revision_id=NEW.revision_id
          AND w.active_attempt_id IS NULL AND p.active_run_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM verification_results WHERE request_id=NEW.request_id)
          AND NEW.issued_at>=q.created_at AND NEW.issued_at<q.deadline
          AND NEW.deadline=q.deadline)
        BEGIN SELECT RAISE(ABORT,'invalid_verification_dispatch'); END""",
    ATTESTATION+'_scope': f"""CREATE TRIGGER {ATTESTATION}_scope BEFORE INSERT ON {ATTESTATION}
        WHEN NOT EXISTS (SELECT 1 FROM verification_dispatches d
          JOIN verification_results r ON r.request_id=d.request_id
          WHERE d.request_id=NEW.request_id AND d.verifier_id=NEW.verifier_id
          AND d.environment_digest=NEW.environment_digest AND d.artifact_key=NEW.artifact_key
          AND d.snapshot_revision=NEW.snapshot_revision AND r.outcome IN ('passed','failed')
          AND r.completed_at=NEW.observed_at AND NEW.observed_at>=d.issued_at
          AND NEW.observed_at<=d.deadline AND r.revision_id=d.revision_id
          AND r.contract_digest=d.contract_digest AND r.policy_digest=d.policy_digest)
        BEGIN SELECT RAISE(ABORT,'invalid_verification_attestation'); END""",
    'release_requires_passing_evidence': f"""CREATE TRIGGER release_requires_passing_evidence BEFORE INSERT ON release_records
        WHEN NOT EXISTS (SELECT 1 FROM {ATTESTATION} t
          JOIN verification_results r ON r.request_id=t.request_id
          JOIN {DISPATCH} d ON d.request_id=t.request_id
          JOIN revision_records v ON v.id=NEW.revision_id AND v.workspace_id=NEW.workspace_id
          WHERE t.request_id=NEW.verification_id AND r.outcome='passed'
          AND r.workspace_id=NEW.workspace_id AND r.revision_id=NEW.revision_id
          AND r.contract_digest=NEW.contract_digest AND r.policy_digest=NEW.policy_digest
          AND d.project_id=NEW.project_id AND d.workspace_id=NEW.workspace_id
          AND d.revision_id=NEW.revision_id AND d.contract_digest=NEW.contract_digest
          AND d.policy_digest=NEW.policy_digest AND d.artifact_key=v.artifact_key
          AND d.snapshot_revision=v.snapshot_revision AND t.artifact_key=d.artifact_key
          AND t.snapshot_revision=d.snapshot_revision)
        BEGIN SELECT RAISE(ABORT,'release_requires_trusted_verification'); END""",
}
for table in (DISPATCH, ATTESTATION):
    for action in ('UPDATE', 'DELETE'):
        name = table + '_no_' + action.lower()
        SCHEMA[name] = f"""CREATE TRIGGER {name} BEFORE {action} ON {table}
            BEGIN SELECT RAISE(ABORT,'immutable_verifier_evidence'); END"""
    name = table + '_no_replace'
    SCHEMA[name] = f"""CREATE TRIGGER {name} BEFORE INSERT ON {table}
        WHEN EXISTS(SELECT 1 FROM {table} WHERE request_id=NEW.request_id)
        BEGIN SELECT RAISE(ABORT,'existing_verifier_evidence'); END"""

MIGRATION_HASH = hashlib.sha256(json.dumps(SCHEMA, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def apply(db):
    from . import MigrationError

    if db.execute('SELECT 1 FROM release_publications WHERE live=1 LIMIT 1').fetchone():
        raise MigrationError('live_untrusted_release')
    journal = db.execute('SELECT version,migration_hash,backup_sha256,applied_at FROM atom_schema_migrations').fetchall()
    db.execute('DROP TABLE atom_schema_migrations')
    db.execute('DROP TRIGGER release_requires_passing_evidence')
    for statement in SCHEMA.values():
        db.execute(statement)
    db.executemany('INSERT INTO atom_schema_migrations VALUES (?,?,?,?)', journal)
