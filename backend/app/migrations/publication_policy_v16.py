"""Offline publication policy migration; no serving/configuration side effects."""
import hashlib
import json

from . import release_v2, verifier_v13, rollback_v14, verification_index_v15


RECORDS = '''CREATE TABLE "release_records" (
        id TEXT NOT NULL PRIMARY KEY, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
        revision_id TEXT NOT NULL, verification_id TEXT,
        contract_digest TEXT, policy_digest TEXT,
        audience TEXT NOT NULL CHECK(audience IN ('owner','public')),
        creator_id TEXT NOT NULL REFERENCES users(id), previous_release_id TEXT,
        created_at INTEGER NOT NULL, verification_mode TEXT NOT NULL DEFAULT 'required'
            CHECK(verification_mode IN ('advisory','required')),
        publication_generation INTEGER NOT NULL
            CHECK(typeof(publication_generation)='integer' AND publication_generation>0),
        CHECK((verification_mode='advisory' AND verification_id IS NULL
                AND contract_digest IS NULL AND policy_digest IS NULL)
            OR (verification_mode='required' AND verification_id IS NOT NULL
                AND contract_digest IS NOT NULL AND policy_digest IS NOT NULL)),
        UNIQUE(id,project_id), UNIQUE(project_id,publication_generation),
        FOREIGN KEY(workspace_id,project_id) REFERENCES revision_workspaces(id,project_id),
        FOREIGN KEY(revision_id,workspace_id) REFERENCES revision_records(id,workspace_id),
        FOREIGN KEY(verification_id,workspace_id,revision_id,contract_digest,policy_digest)
        REFERENCES verification_results(request_id,workspace_id,revision_id,contract_digest,policy_digest),
        FOREIGN KEY(previous_release_id,project_id) REFERENCES release_records(id,project_id))'''

SCHEMA = {
    'atom_schema_migrations': verification_index_v15.SCHEMA['atom_schema_migrations'].replace(
        'CHECK(version IN (1,2,3,4,5,6,7,8,9,10,11,12,13,14,15))',
        'CHECK(version IN (1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16))'),
    'release_records': RECORDS,
    'release_rollback_sources': rollback_v14.SCHEMA['release_rollback_sources'].replace(
        "CREATE TABLE release_rollback_sources", 'CREATE TABLE "release_rollback_sources"', 1).replace(
        ' AND source_release_id<>displaced_release_id', ''),
    'release_requires_passing_evidence': verifier_v13.SCHEMA['release_requires_passing_evidence'].replace(
        'WHEN NOT EXISTS', "WHEN NEW.verification_mode='required' AND NOT EXISTS", 1),
    'release_revision_scope': '''CREATE TRIGGER release_revision_scope BEFORE INSERT ON release_records
        WHEN NOT EXISTS (SELECT 1 FROM revision_records r
          JOIN projects p ON p.id=r.project_id
          WHERE r.id=NEW.revision_id AND r.workspace_id=NEW.workspace_id
            AND r.project_id=NEW.project_id AND p.user_id=NEW.creator_id)
        BEGIN SELECT RAISE(ABORT,'invalid_release_revision_scope'); END''',
    'release_records_project_history': '''CREATE INDEX release_records_project_history
        ON release_records(project_id,publication_generation DESC)''',
    'release_generation_scope': '''CREATE TRIGGER release_generation_scope BEFORE INSERT ON release_records
        WHEN NEW.publication_generation != coalesce((SELECT generation FROM release_publications
             WHERE project_id=NEW.project_id),0)+1
        BEGIN SELECT RAISE(ABORT,'invalid_release_generation'); END''',
    'release_rollback_sources_scope': '''CREATE TRIGGER release_rollback_sources_scope
        BEFORE INSERT ON release_rollback_sources
        WHEN NOT EXISTS (SELECT 1 FROM release_records n
          JOIN release_records s ON s.id=NEW.source_release_id AND s.project_id=n.project_id
          JOIN release_publications p ON p.project_id=n.project_id
          JOIN command_receipts c ON c.project_id=n.project_id AND c.key='rollback:'||NEW.command_id
          JOIN security_audit_events a ON a.scope_kind='project' AND a.scope_id=n.project_id
              AND a.event_kind='release.published' AND a.release_id=n.id
              AND a.operation_id=n.id AND a.publication_generation=NEW.generation
          WHERE n.id=NEW.new_release_id AND n.project_id=NEW.project_id
          AND n.previous_release_id=NEW.displaced_release_id
          AND n.workspace_id=s.workspace_id AND n.revision_id=s.revision_id
          AND n.audience=s.audience
          AND (n.verification_mode='advisory' OR (
               s.verification_mode='required'
               AND n.verification_id IS s.verification_id
               AND n.contract_digest IS s.contract_digest
               AND n.policy_digest IS s.policy_digest
               AND EXISTS (SELECT 1 FROM verification_attestations t
                           WHERE t.request_id=s.verification_id)))
          AND p.release_id=n.id AND p.generation=NEW.generation AND p.live=1
          AND length(c.digest)=64 AND json_valid(c.response_json)
          AND json_extract(c.response_json,'$.release_id')=n.id
          AND json_extract(c.response_json,'$.source_release_id')=s.id
          AND json_extract(c.response_json,'$.displaced_release_id')=NEW.displaced_release_id
          AND json_extract(c.response_json,'$.generation')=NEW.generation
          AND json_extract(c.response_json,'$.slug')=p.slug)
        BEGIN SELECT RAISE(ABORT,'invalid_release_rollback_source'); END''',
}
MIGRATION_HASH = hashlib.sha256(json.dumps(SCHEMA, sort_keys=True,
                                           separators=(',', ':')).encode()).hexdigest()


def apply(db):
    journal = db.execute('SELECT version,migration_hash,backup_sha256,applied_at '
                         'FROM atom_schema_migrations').fetchall()
    db.execute('DROP TABLE atom_schema_migrations')
    db.execute(SCHEMA['atom_schema_migrations'])
    db.executemany('INSERT INTO atom_schema_migrations VALUES (?,?,?,?)', journal)
    # Drop the inbound trigger during the rebuild, preserving its rows and FKs.
    db.execute('DROP TRIGGER release_rollback_sources_scope')
    db.execute(RECORDS.replace('CREATE TABLE "release_records"', 'CREATE TABLE release_records_next', 1))
    db.execute('''INSERT INTO release_records_next
        (id,project_id,workspace_id,revision_id,verification_id,contract_digest,
         policy_digest,audience,creator_id,previous_release_id,created_at,verification_mode,publication_generation)
        SELECT r.id,r.project_id,r.workspace_id,r.revision_id,r.verification_id,r.contract_digest,
               r.policy_digest,r.audience,r.creator_id,r.previous_release_id,r.created_at,'required',
               CASE WHEN json_valid(c.response_json)
                    AND json_extract(c.response_json,'$.release_id')=r.id
                    THEN json_extract(c.response_json,'$.generation') END
        FROM release_records r
        LEFT JOIN release_rollback_sources s ON s.new_release_id=r.id AND s.project_id=r.project_id
        LEFT JOIN command_receipts c ON c.project_id=r.project_id
          AND c.key=CASE WHEN s.command_id IS NULL THEN 'release:'||r.id
                        ELSE 'rollback:'||s.command_id END''')
    db.execute('DROP TABLE release_records')
    db.execute('ALTER TABLE release_records_next RENAME TO release_records')
    db.execute(SCHEMA['release_rollback_sources'].replace(
        'CREATE TABLE "release_rollback_sources"', 'CREATE TABLE release_rollback_sources_next', 1))
    db.execute('INSERT INTO release_rollback_sources_next SELECT * FROM release_rollback_sources')
    db.execute('DROP TABLE release_rollback_sources')
    db.execute('ALTER TABLE release_rollback_sources_next RENAME TO release_rollback_sources')
    for action in ('update', 'delete'):
        db.execute(rollback_v14.SCHEMA['release_rollback_sources_no_' + action])
    for action in ('update', 'delete'):
        db.execute(release_v2.SCHEMA['release_records_no_' + action])
    for name, statement in SCHEMA.items():
        if name not in ('atom_schema_migrations', 'release_records', 'release_rollback_sources'):
            db.execute(statement)
