"""Immutable additive schema definition for the supported demo baseline."""
import hashlib
import json
import uuid

BASELINE_HASH = "8c930a956d03fcdeb7ae4220b75e255e3f7a5ec043905d1d2c4b911417d68f75"
HASH_CHECK = "length({0})=64 AND {0} NOT GLOB '*[^0-9a-f]*'"

SCHEMA = {
    "atom_schema_migrations": """CREATE TABLE atom_schema_migrations (
        version INTEGER PRIMARY KEY CHECK(version=1), migration_hash TEXT NOT NULL CHECK(%s),
        backup_sha256 TEXT NOT NULL CHECK(%s), applied_at INTEGER NOT NULL)""" % (HASH_CHECK.format("migration_hash"), HASH_CHECK.format("backup_sha256")),
    "revision_run_scope": "CREATE UNIQUE INDEX revision_run_scope ON runs(id,project_id)",
    "revision_workspaces": """CREATE TABLE revision_workspaces (
        id TEXT NOT NULL PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
        heat_id TEXT UNIQUE REFERENCES race_heats(id), current_revision_id TEXT,
        generation INTEGER NOT NULL DEFAULT 0 CHECK(typeof(generation)='integer' AND generation>=0),
        active_attempt_id TEXT, UNIQUE(id,project_id),
        FOREIGN KEY(current_revision_id,id) REFERENCES revision_records(id,workspace_id) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(active_attempt_id,id) REFERENCES revision_attempts(id,workspace_id) DEFERRABLE INITIALLY DEFERRED)""",
    "revision_main_workspace": "CREATE UNIQUE INDEX revision_main_workspace ON revision_workspaces(project_id) WHERE heat_id IS NULL",
    "revision_artifacts": """CREATE TABLE revision_artifacts (
        key TEXT NOT NULL PRIMARY KEY CHECK(%s), revision TEXT NOT NULL CHECK(%s),
        size INTEGER NOT NULL CHECK(typeof(size)='integer' AND size>=14 AND size<=68157454),
        created_at INTEGER NOT NULL, UNIQUE(key,revision))""" % (HASH_CHECK.format("key"), HASH_CHECK.format("revision")),
    "revision_attempts": """CREATE TABLE revision_attempts (
        id TEXT NOT NULL PRIMARY KEY, workspace_id TEXT NOT NULL, project_id TEXT NOT NULL, run_id TEXT NOT NULL,
        generation INTEGER NOT NULL CHECK(typeof(generation)='integer' AND generation>0),
        base_revision_id TEXT NOT NULL, broker_attempt_id TEXT UNIQUE, grant_id TEXT UNIQUE,
        deadline INTEGER NOT NULL CHECK(typeof(deadline)='integer' AND deadline>0),
        state TEXT NOT NULL CHECK(state IN ('active','cancel_requested','closed')),
        termination_state TEXT NOT NULL CHECK(termination_state IN ('pending','confirmed','unknown')),
        outcome TEXT CHECK(outcome IN ('succeeded','failed','cancelled','timed_out')),
        created_at INTEGER NOT NULL, closed_at INTEGER,
        CHECK(state!='closed' OR (termination_state='confirmed' AND outcome IS NOT NULL AND closed_at IS NOT NULL)),
        UNIQUE(id,workspace_id), UNIQUE(workspace_id,generation),
        FOREIGN KEY(workspace_id,project_id) REFERENCES revision_workspaces(id,project_id),
        FOREIGN KEY(run_id,project_id) REFERENCES runs(id,project_id),
        FOREIGN KEY(base_revision_id,workspace_id) REFERENCES revision_records(id,workspace_id))""",
    "revision_records": """CREATE TABLE revision_records (
        id TEXT NOT NULL PRIMARY KEY, workspace_id TEXT NOT NULL, project_id TEXT NOT NULL,
        parent_revision_id TEXT, artifact_key TEXT NOT NULL, snapshot_revision TEXT NOT NULL,
        producing_attempt_id TEXT UNIQUE, created_at INTEGER NOT NULL,
        CHECK((producing_attempt_id IS NULL AND parent_revision_id IS NULL) OR
              (producing_attempt_id IS NOT NULL AND parent_revision_id IS NOT NULL)),
        UNIQUE(id,workspace_id), UNIQUE(id,producing_attempt_id,workspace_id),
        FOREIGN KEY(workspace_id,project_id) REFERENCES revision_workspaces(id,project_id),
        FOREIGN KEY(parent_revision_id,workspace_id) REFERENCES revision_records(id,workspace_id),
        FOREIGN KEY(producing_attempt_id,workspace_id) REFERENCES revision_attempts(id,workspace_id),
        FOREIGN KEY(artifact_key,snapshot_revision) REFERENCES revision_artifacts(key,revision))""",
    "revision_one_root": "CREATE UNIQUE INDEX revision_one_root ON revision_records(workspace_id) WHERE parent_revision_id IS NULL",
    "revision_receipts": """CREATE TABLE revision_receipts (
        attempt_id TEXT NOT NULL PRIMARY KEY, workspace_id TEXT NOT NULL, revision_id TEXT NOT NULL UNIQUE,
        request_hash TEXT NOT NULL CHECK(%s), created_at INTEGER NOT NULL,
        FOREIGN KEY(attempt_id,workspace_id) REFERENCES revision_attempts(id,workspace_id),
        FOREIGN KEY(revision_id,attempt_id,workspace_id) REFERENCES revision_records(id,producing_attempt_id,workspace_id))""" % HASH_CHECK.format("request_hash"),
    "revision_outbox": """CREATE TABLE revision_outbox (
        id TEXT NOT NULL PRIMARY KEY, workspace_id TEXT NOT NULL, revision_id TEXT NOT NULL UNIQUE,
        event_kind TEXT NOT NULL CHECK(event_kind='revision.registered'), created_at INTEGER NOT NULL, delivered_at INTEGER,
        FOREIGN KEY(revision_id,workspace_id) REFERENCES revision_records(id,workspace_id))""",
    "revision_heat_scope": """CREATE TRIGGER revision_heat_scope BEFORE INSERT ON revision_workspaces
        WHEN NEW.heat_id IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM race_heats h JOIN races r ON r.id=h.race_id WHERE h.id=NEW.heat_id AND r.project_id=NEW.project_id)
        BEGIN SELECT RAISE(ABORT,'workspace_heat_scope'); END""",
    "revision_attempt_scope": """CREATE TRIGGER revision_attempt_scope BEFORE INSERT ON revision_attempts
        WHEN NOT EXISTS (SELECT 1 FROM runs r JOIN revision_workspaces w ON w.id=NEW.workspace_id
        WHERE r.id=NEW.run_id AND r.project_id=NEW.project_id AND w.project_id=NEW.project_id AND r.heat_id IS w.heat_id)
        BEGIN SELECT RAISE(ABORT,'attempt_workspace_scope'); END""",
    "revision_workspace_immutable": """CREATE TRIGGER revision_workspace_immutable BEFORE UPDATE OF id,project_id,heat_id ON revision_workspaces
        BEGIN SELECT RAISE(ABORT,'immutable_workspace_scope'); END""",
    "revision_attempt_immutable": """CREATE TRIGGER revision_attempt_immutable BEFORE UPDATE OF id,workspace_id,project_id,run_id,generation,base_revision_id,deadline ON revision_attempts
        BEGIN SELECT RAISE(ABORT,'immutable_attempt_scope'); END""",
    "revision_run_immutable": """CREATE TRIGGER revision_run_immutable BEFORE UPDATE OF project_id,heat_id ON runs
        WHEN EXISTS (SELECT 1 FROM revision_attempts WHERE run_id=OLD.id)
        BEGIN SELECT RAISE(ABORT,'run_scope_in_use'); END""",
    "revision_heat_immutable": """CREATE TRIGGER revision_heat_immutable BEFORE UPDATE OF race_id ON race_heats
        WHEN EXISTS (SELECT 1 FROM revision_workspaces WHERE heat_id=OLD.id)
        BEGIN SELECT RAISE(ABORT,'heat_scope_in_use'); END""",
    "revision_race_immutable": """CREATE TRIGGER revision_race_immutable BEFORE UPDATE OF project_id ON races
        WHEN EXISTS (SELECT 1 FROM revision_workspaces w JOIN race_heats h ON h.id=w.heat_id WHERE h.race_id=OLD.id)
        BEGIN SELECT RAISE(ABORT,'race_scope_in_use'); END""",
}
for table in ("revision_records", "revision_artifacts", "revision_receipts"):
    for operation in ("UPDATE", "DELETE"):
        name = table + "_no_" + operation.lower()
        SCHEMA[name] = f"CREATE TRIGGER {name} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_revision_evidence'); END"

MIGRATION_HASH = hashlib.sha256(json.dumps(SCHEMA, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def apply(db):
    for statement in SCHEMA.values():
        db.execute(statement)
    for (project_id,) in db.execute("SELECT id FROM projects ORDER BY id").fetchall():
        db.execute("INSERT INTO revision_workspaces(id,project_id) VALUES (?,?)", (uuid.uuid4().hex, project_id))
    for heat_id, project_id in db.execute("SELECT h.id,r.project_id FROM race_heats h JOIN races r ON r.id=h.race_id ORDER BY h.id").fetchall():
        db.execute("INSERT INTO revision_workspaces(id,project_id,heat_id) VALUES (?,?,?)", (uuid.uuid4().hex, project_id, heat_id))
