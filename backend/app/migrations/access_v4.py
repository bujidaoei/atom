"""Durable source sessions and hash-only content access; offline schema only."""
import hashlib
import json

from .content_v3 import SCHEMA as V3_SCHEMA


def digest(column):
    return f"length({column})=64 AND {column} NOT GLOB '*[^0-9a-f]*'"


def lifetime(maximum=None):
    return ("typeof(created_at)='integer' AND created_at>=0 AND "
            "typeof(expires_at)='integer' AND expires_at>created_at" +
            (f" AND expires_at-created_at<={maximum}" if maximum else ""))


SCHEMA = {
    'atom_schema_migrations': V3_SCHEMA['atom_schema_migrations'].replace('CHECK(version IN (1,2,3))','CHECK(version IN (1,2,3,4))'),
    'console_sessions': f"""CREATE TABLE console_sessions (
        id TEXT NOT NULL PRIMARY KEY CHECK(length(id)=32 AND id NOT GLOB '*[^0-9a-f]*'),
        user_id TEXT NOT NULL REFERENCES users(id), created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
        revoked_at INTEGER CHECK(revoked_at IS NULL OR (typeof(revoked_at)='integer' AND revoked_at>=created_at)),
        CHECK({lifetime()}), UNIQUE(id,user_id))""",
    'content_bootstraps': f"""CREATE TABLE content_bootstraps (
        nonce_hash TEXT NOT NULL PRIMARY KEY CHECK({digest('nonce_hash')}),
        binding_id TEXT NOT NULL REFERENCES content_bindings(id),
        created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
        consumed_at INTEGER CHECK(consumed_at IS NULL OR (typeof(consumed_at)='integer' AND consumed_at>=created_at AND consumed_at<expires_at)),
        CHECK({lifetime(120)}), UNIQUE(nonce_hash,binding_id))""",
    'content_handoffs': f"""CREATE TABLE content_handoffs (
        token_hash TEXT NOT NULL PRIMARY KEY CHECK({digest('token_hash')}),
        bootstrap_hash TEXT NOT NULL UNIQUE, binding_id TEXT NOT NULL,
        viewer_id TEXT NOT NULL, source_session_id TEXT NOT NULL,
        publication_generation INTEGER NOT NULL CHECK(typeof(publication_generation)='integer' AND publication_generation>0),
        created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
        consumed_at INTEGER CHECK(consumed_at IS NULL OR (typeof(consumed_at)='integer' AND consumed_at>=created_at AND consumed_at<expires_at)),
        CHECK({lifetime(120)}),
        FOREIGN KEY(bootstrap_hash,binding_id) REFERENCES content_bootstraps(nonce_hash,binding_id),
        FOREIGN KEY(source_session_id,viewer_id) REFERENCES console_sessions(id,user_id),
        UNIQUE(token_hash,binding_id,viewer_id,source_session_id,publication_generation))""",
    'content_sessions': f"""CREATE TABLE content_sessions (
        token_hash TEXT NOT NULL PRIMARY KEY CHECK({digest('token_hash')}),
        handoff_hash TEXT NOT NULL UNIQUE, binding_id TEXT NOT NULL,
        viewer_id TEXT NOT NULL, source_session_id TEXT NOT NULL,
        publication_generation INTEGER NOT NULL,
        created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
        revoked_at INTEGER CHECK(revoked_at IS NULL OR (typeof(revoked_at)='integer' AND revoked_at>=created_at)),
        CHECK({lifetime(900)}),
        FOREIGN KEY(handoff_hash,binding_id,viewer_id,source_session_id,publication_generation)
            REFERENCES content_handoffs(token_hash,binding_id,viewer_id,source_session_id,publication_generation))""",
    'content_handoff_source': """CREATE TRIGGER content_handoff_source BEFORE INSERT ON content_handoffs
        WHEN NOT EXISTS (SELECT 1 FROM console_sessions s JOIN content_bootstraps b ON b.nonce_hash=NEW.bootstrap_hash
          WHERE s.id=NEW.source_session_id AND s.user_id=NEW.viewer_id AND s.revoked_at IS NULL
          AND s.created_at<=NEW.created_at AND s.expires_at>=NEW.expires_at
          AND b.binding_id=NEW.binding_id AND b.consumed_at IS NULL
          AND b.created_at<=NEW.created_at AND b.expires_at>=NEW.expires_at)
        BEGIN SELECT RAISE(ABORT,'invalid_handoff_source'); END""",
    'content_session_source': """CREATE TRIGGER content_session_source BEFORE INSERT ON content_sessions
        WHEN NOT EXISTS (SELECT 1 FROM content_handoffs h
          JOIN content_bootstraps b ON b.nonce_hash=h.bootstrap_hash
          JOIN console_sessions s ON s.id=h.source_session_id
          WHERE h.token_hash=NEW.handoff_hash AND h.consumed_at=NEW.created_at AND b.consumed_at=NEW.created_at
          AND h.expires_at>NEW.created_at AND s.revoked_at IS NULL AND s.expires_at>=NEW.expires_at)
        BEGIN SELECT RAISE(ABORT,'invalid_content_session_source'); END""",
    'console_sessions_user_expiry': 'CREATE INDEX console_sessions_user_expiry ON console_sessions(user_id,expires_at)',
    'content_bootstraps_binding_expiry': 'CREATE INDEX content_bootstraps_binding_expiry ON content_bootstraps(binding_id,expires_at)',
    'content_handoffs_viewer_expiry': 'CREATE INDEX content_handoffs_viewer_expiry ON content_handoffs(viewer_id,binding_id,expires_at)',
    'content_sessions_source_expiry': 'CREATE INDEX content_sessions_source_expiry ON content_sessions(source_session_id,expires_at)',
}

for table, scope, terminal in (
    ('console_sessions','id,user_id,created_at,expires_at','revoked_at'),
    ('content_bootstraps','nonce_hash,binding_id,created_at,expires_at','consumed_at'),
    ('content_handoffs','token_hash,bootstrap_hash,binding_id,viewer_id,source_session_id,publication_generation,created_at,expires_at','consumed_at'),
    ('content_sessions','token_hash,handoff_hash,binding_id,viewer_id,source_session_id,publication_generation,created_at,expires_at','revoked_at'),
):
    SCHEMA[table+'_immutable'] = f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OF {scope} ON {table}
        BEGIN SELECT RAISE(ABORT,'immutable_access_scope'); END"""
    SCHEMA[table+'_terminal'] = f"""CREATE TRIGGER {table}_terminal BEFORE UPDATE OF {terminal} ON {table}
        WHEN OLD.{terminal} IS NOT NULL OR NEW.{terminal} IS NULL
        BEGIN SELECT RAISE(ABORT,'access_already_terminal'); END"""

MIGRATION_HASH = hashlib.sha256(json.dumps(SCHEMA,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def apply(db):
    journal = db.execute('SELECT version,migration_hash,backup_sha256,applied_at FROM atom_schema_migrations').fetchall()
    db.execute('DROP TABLE atom_schema_migrations')
    for statement in SCHEMA.values():
        db.execute(statement)
    db.executemany('INSERT INTO atom_schema_migrations VALUES (?,?,?,?)',journal)
