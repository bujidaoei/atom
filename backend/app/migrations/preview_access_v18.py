"""One-use owner preview grants and revocable exact-revision sessions."""
import hashlib
import json

from .project_origins_v17 import SCHEMA as V17_SCHEMA


_HASH = "length({name})=64 AND {name} NOT GLOB '*[^0-9a-f]*'"

SCHEMA = {
    'atom_schema_migrations': V17_SCHEMA['atom_schema_migrations'].replace(
        'CHECK(version IN (1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17))',
        'CHECK(version IN (1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18))'),
    'preview_handoffs': '''CREATE TABLE preview_handoffs (
        token_hash TEXT NOT NULL PRIMARY KEY CHECK(%s),
        project_id TEXT NOT NULL, revision_id TEXT NOT NULL,
        owner_id TEXT NOT NULL, source_session_id TEXT NOT NULL,
        created_at INTEGER NOT NULL CHECK(typeof(created_at)='integer' AND created_at>=0),
        expires_at INTEGER NOT NULL CHECK(typeof(expires_at)='integer' AND
            expires_at-created_at BETWEEN 1 AND 120),
        consumed_at INTEGER CHECK(consumed_at IS NULL OR
            (typeof(consumed_at)='integer' AND consumed_at>=created_at AND
             consumed_at<expires_at)))''' % _HASH.format(name='token_hash'),
    'preview_handoffs_scope': '''CREATE TRIGGER preview_handoffs_scope
        BEFORE INSERT ON preview_handoffs
        WHEN NOT EXISTS (SELECT 1 FROM projects p
          JOIN revision_records r ON r.project_id=p.id
          JOIN console_sessions s ON s.id=NEW.source_session_id AND s.user_id=p.user_id
          JOIN project_origin_ports o ON o.project_id=p.id AND o.purpose='preview'
          WHERE p.id=NEW.project_id AND r.id=NEW.revision_id AND p.user_id=NEW.owner_id)
        BEGIN SELECT RAISE(ABORT,'invalid_preview_scope'); END''',
    'preview_handoffs_identity': '''CREATE TRIGGER preview_handoffs_identity
        BEFORE UPDATE ON preview_handoffs
        WHEN OLD.consumed_at IS NOT NULL OR NEW.token_hash!=OLD.token_hash
          OR NEW.project_id!=OLD.project_id OR NEW.revision_id!=OLD.revision_id
          OR NEW.owner_id!=OLD.owner_id OR NEW.source_session_id!=OLD.source_session_id
          OR NEW.created_at!=OLD.created_at OR NEW.expires_at!=OLD.expires_at
          OR NEW.consumed_at IS NULL
        BEGIN SELECT RAISE(ABORT,'immutable_preview_handoff'); END''',
    'preview_handoffs_expiry': '''CREATE INDEX preview_handoffs_expiry
        ON preview_handoffs(expires_at,project_id)''',
    'preview_sessions': '''CREATE TABLE preview_sessions (
        token_hash TEXT NOT NULL PRIMARY KEY CHECK(%s),
        handoff_hash TEXT NOT NULL UNIQUE CHECK(%s),
        project_id TEXT NOT NULL, revision_id TEXT NOT NULL,
        owner_id TEXT NOT NULL, source_session_id TEXT NOT NULL,
        created_at INTEGER NOT NULL CHECK(typeof(created_at)='integer' AND created_at>=0),
        expires_at INTEGER NOT NULL CHECK(typeof(expires_at)='integer' AND
            expires_at-created_at BETWEEN 1 AND 900),
        revoked_at INTEGER CHECK(revoked_at IS NULL OR
            (typeof(revoked_at)='integer' AND revoked_at>=created_at)))''' %
            (_HASH.format(name='token_hash'), _HASH.format(name='handoff_hash')),
    'preview_sessions_scope': '''CREATE TRIGGER preview_sessions_scope
        BEFORE INSERT ON preview_sessions
        WHEN NOT EXISTS (SELECT 1 FROM preview_handoffs h
          WHERE h.token_hash=NEW.handoff_hash AND h.project_id=NEW.project_id
            AND h.revision_id=NEW.revision_id AND h.owner_id=NEW.owner_id
            AND h.source_session_id=NEW.source_session_id AND h.consumed_at IS NOT NULL)
        BEGIN SELECT RAISE(ABORT,'invalid_preview_session'); END''',
    'preview_sessions_identity': '''CREATE TRIGGER preview_sessions_identity
        BEFORE UPDATE ON preview_sessions
        WHEN OLD.revoked_at IS NOT NULL OR NEW.token_hash!=OLD.token_hash
          OR NEW.handoff_hash!=OLD.handoff_hash OR NEW.project_id!=OLD.project_id
          OR NEW.revision_id!=OLD.revision_id OR NEW.owner_id!=OLD.owner_id
          OR NEW.source_session_id!=OLD.source_session_id
          OR NEW.created_at!=OLD.created_at OR NEW.expires_at!=OLD.expires_at
          OR NEW.revoked_at IS NULL
        BEGIN SELECT RAISE(ABORT,'immutable_preview_session'); END''',
    'preview_sessions_expiry': '''CREATE INDEX preview_sessions_expiry
        ON preview_sessions(expires_at,project_id)''',
    'preview_audit_events': '''CREATE TABLE preview_audit_events (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL UNIQUE CHECK(length(event_id)=32 AND
            event_id NOT GLOB '*[^0-9a-f]*'),
        event_kind TEXT NOT NULL CHECK(event_kind IN
            ('preview.handoff.issued','preview.session.created')),
        project_id TEXT NOT NULL, revision_id TEXT NOT NULL,
        owner_id TEXT NOT NULL, source_session_id TEXT NOT NULL,
        occurred_at INTEGER NOT NULL CHECK(typeof(occurred_at)='integer' AND occurred_at>=0))''',
    'preview_audit_scope_sequence': '''CREATE INDEX preview_audit_scope_sequence
        ON preview_audit_events(project_id,sequence)''',
    'preview_audit_no_update': '''CREATE TRIGGER preview_audit_no_update
        BEFORE UPDATE ON preview_audit_events
        BEGIN SELECT RAISE(ABORT,'immutable_preview_audit'); END''',
    'preview_audit_no_delete': '''CREATE TRIGGER preview_audit_no_delete
        BEFORE DELETE ON preview_audit_events
        BEGIN SELECT RAISE(ABORT,'immutable_preview_audit'); END''',
}

MIGRATION_HASH = hashlib.sha256(json.dumps(SCHEMA, sort_keys=True,
                                           separators=(',', ':')).encode()).hexdigest()


def apply(db):
    journal = db.execute('SELECT version,migration_hash,backup_sha256,applied_at '
                         'FROM atom_schema_migrations').fetchall()
    db.execute('DROP TABLE atom_schema_migrations')
    for statement in SCHEMA.values():
        db.execute(statement)
    db.executemany('INSERT INTO atom_schema_migrations VALUES (?,?,?,?)', journal)
