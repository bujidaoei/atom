"""Host-local durable ownership. No Docker calls or control-plane authorization.

Grant inputs must already be cryptographically verified. Administrative methods
are for the trusted lifecycle service, never exposed with runtime grant authority.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
import time
import uuid

from .grants import Grant

_REVISION = re.compile(r"[0-9a-f]{64}\Z")
_EDGES = {"intent": "provisioning", "provisioning": "ready", "ready": "quiescing", "quiescing": "checkpointed"}
_SCHEMA_V1 = {
    "broker_meta": """CREATE TABLE broker_meta (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), broker_id TEXT NOT NULL)""",
    "attempts": """CREATE TABLE attempts (
        id TEXT PRIMARY KEY, grant_id TEXT NOT NULL UNIQUE, grant_fingerprint TEXT NOT NULL,
        org TEXT NOT NULL, project TEXT NOT NULL, run TEXT NOT NULL, attempt TEXT NOT NULL,
        fence INTEGER NOT NULL CHECK(fence>0), base_revision TEXT NOT NULL, deadline INTEGER NOT NULL,
        container_name TEXT NOT NULL UNIQUE,
        state TEXT NOT NULL CHECK(state IN ('intent','provisioning','ready','quiescing','checkpointed',
                                           'terminating','termination_unknown','terminated')),
        version INTEGER NOT NULL CHECK(version>0), checkpoint_revision TEXT,
        created_at REAL NOT NULL, updated_at REAL NOT NULL,
        UNIQUE(org,project,run,attempt))""",
    "heads": """CREATE TABLE heads (
        org TEXT NOT NULL, project TEXT NOT NULL, run TEXT NOT NULL,
        attempt_id TEXT NOT NULL REFERENCES attempts(id), fence INTEGER NOT NULL CHECK(fence>0),
        PRIMARY KEY(org,project,run))""",
    "revocations": """CREATE TABLE revocations (grant_id TEXT PRIMARY KEY, revoked_at REAL NOT NULL)""",
}
_SCHEMA = {**_SCHEMA_V1, "orphans": """CREATE TABLE orphans (
    id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('observed','termination_unknown','terminated')),
    version INTEGER NOT NULL CHECK(version>0), created_at REAL NOT NULL, updated_at REAL NOT NULL)"""}


class RegistryError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Attempt:
    id: str
    grant_id: str
    grant_fingerprint: str
    org: str
    project: str
    run: str
    attempt: str
    fence: int
    base_revision: str
    deadline: int
    container_name: str
    state: str
    version: int
    checkpoint_revision: str | None
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class Orphan:
    id: str
    attempt_id: str
    state: str
    version: int
    created_at: float
    updated_at: float


class Registry:
    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time, lock_timeout: float = 3):
        self.path = Path(path)
        if self.path.is_symlink() or not self.path.parent.is_dir():
            raise RegistryError("invalid_registry_path")
        if isinstance(lock_timeout, bool) or not isinstance(lock_timeout, (int, float)) or not 0 < lock_timeout <= 10:
            raise RegistryError("invalid_lock_timeout")
        self._clock = clock
        self._lock_timeout = lock_timeout
        with self._transaction() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            schema = {row["name"]: row["sql"] for row in db.execute(
                "SELECT name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
            if version == 0 and not schema:
                for statement in _SCHEMA.values():
                    db.execute(statement)
                db.execute("INSERT INTO broker_meta VALUES (1,?)", (uuid.uuid4().hex,))
                db.execute("PRAGMA user_version=2")
            else:
                normalize = lambda sql: " ".join(sql.split()).casefold()
                expected_schema = _SCHEMA_V1 if version == 1 else _SCHEMA
                if version not in (1, 2) or set(schema) != set(expected_schema) or any(
                    normalize(schema[name]) != normalize(expected) for name, expected in expected_schema.items()
                ):
                    raise RegistryError("unsupported_schema")
                if version == 1:
                    db.execute(_SCHEMA["orphans"])
                    db.execute("PRAGMA user_version=2")
            identity = db.execute("SELECT broker_id FROM broker_meta WHERE singleton=1").fetchone()
            if identity is None or not isinstance(identity[0], str) or not re.fullmatch(r"[0-9a-f]{32}", identity[0]):
                raise RegistryError("invalid_registry_identity")
            self.broker_id = identity[0]
        # Journal mode cannot be changed inside a transaction. Validate schema first.
        with self._connection() as db:
            if db.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() != "wal":
                raise RegistryError("registry_unavailable")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        db = None
        try:
            db = sqlite3.connect(self.path, timeout=self._lock_timeout, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            yield db
        except sqlite3.Error:
            raise RegistryError("registry_unavailable") from None
        finally:
            if db is not None:
                db.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def _by_id(db: sqlite3.Connection, attempt_id: str) -> Attempt:
        row = db.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        if row is None:
            raise RegistryError("attempt_not_found")
        return Attempt(**dict(row))

    def _grant_checks(self, db: sqlite3.Connection, grant: Grant) -> None:
        if not grant.iat <= self._clock() < grant.exp:
            raise RegistryError("grant_expired")
        if db.execute("SELECT 1 FROM revocations WHERE grant_id=?", (grant.jti,)).fetchone():
            raise RegistryError("grant_revoked")

    def _owned(self, db: sqlite3.Connection, grant: Grant) -> Attempt:
        self._grant_checks(db, grant)
        row = db.execute("SELECT * FROM attempts WHERE grant_id=?", (grant.jti,)).fetchone()
        if row is None:
            raise RegistryError("attempt_not_found")
        attempt = Attempt(**dict(row))
        if attempt.grant_fingerprint != grant.fingerprint():
            raise RegistryError("grant_conflict")
        head = db.execute("SELECT attempt_id,fence FROM heads WHERE org=? AND project=? AND run=?",
                          (grant.org, grant.project, grant.run)).fetchone()
        if head is None or head["attempt_id"] != attempt.id or head["fence"] != grant.fence:
            raise RegistryError("stale_fence")
        return attempt

    def admit(self, grant: Grant) -> Attempt:
        with self._transaction() as db:
            self._grant_checks(db, grant)
            if db.execute("SELECT 1 FROM attempts WHERE grant_id=?", (grant.jti,)).fetchone():
                return self._owned(db, grant)
            scope = (grant.org, grant.project, grant.run)
            if db.execute("SELECT 1 FROM attempts WHERE org=? AND project=? AND run=? AND attempt=?",
                          (*scope, grant.attempt)).fetchone():
                raise RegistryError("grant_conflict")
            head = db.execute("SELECT attempt_id,fence FROM heads WHERE org=? AND project=? AND run=?", scope).fetchone()
            if head:
                if grant.fence <= head["fence"]:
                    raise RegistryError("stale_fence")
                if self._by_id(db, head["attempt_id"]).state != "terminated":
                    raise RegistryError("predecessor_unterminated")
            identity = uuid.uuid4().hex
            now = self._clock()
            db.execute("""INSERT INTO attempts
                (id,grant_id,grant_fingerprint,org,project,run,attempt,fence,base_revision,deadline,
                 container_name,state,version,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,'intent',1,?,?)""",
                (identity, grant.jti, grant.fingerprint(), *scope, grant.attempt, grant.fence,
                 grant.base_revision, grant.exp, f"atom-sbox-{self.broker_id[:12]}-{identity}", now, now))
            db.execute("""INSERT INTO heads VALUES (?,?,?,?,?) ON CONFLICT(org,project,run)
                DO UPDATE SET attempt_id=excluded.attempt_id,fence=excluded.fence""", (*scope, identity, grant.fence))
            return self._by_id(db, identity)

    def authorize(self, grant: Grant) -> Attempt:
        with self._transaction() as db:
            attempt = self._owned(db, grant)
            if attempt.state != "ready":
                raise RegistryError("attempt_not_ready")
            return attempt

    @staticmethod
    def _version(attempt: Attempt, expected: int) -> None:
        if type(expected) is not int or expected != attempt.version:
            raise RegistryError("version_conflict")

    def transition(self, grant: Grant, expected_version: int, target: str, *, revision: str | None = None) -> Attempt:
        with self._transaction() as db:
            attempt = self._owned(db, grant)
            self._version(attempt, expected_version)
            if not isinstance(target, str) or _EDGES.get(attempt.state) != target:
                raise RegistryError("invalid_transition")
            if target == "checkpointed":
                if not isinstance(revision, str) or not _REVISION.fullmatch(revision):
                    raise RegistryError("invalid_revision")
            elif revision is not None:
                raise RegistryError("invalid_revision")
            db.execute("UPDATE attempts SET state=?,version=version+1,checkpoint_revision=?,updated_at=? WHERE id=?",
                       (target, revision, self._clock(), attempt.id))
            return self._by_id(db, attempt.id)

    def _terminate(self, db: sqlite3.Connection, attempt: Attempt) -> Attempt:
        if attempt.state not in {"terminating", "termination_unknown", "terminated"}:
            db.execute("UPDATE attempts SET state='terminating',version=version+1,updated_at=? WHERE id=?",
                       (self._clock(), attempt.id))
        return self._by_id(db, attempt.id)

    def request_termination(self, attempt_id: str) -> Attempt:
        """Trusted admin intent; legal even after expiry or revocation."""
        with self._transaction() as db:
            return self._terminate(db, self._by_id(db, attempt_id))

    def record_termination(self, attempt_id: str, expected_version: int, *, confirmed: bool) -> Attempt:
        """Record driver evidence; this function does not verify OS termination."""
        if type(confirmed) is not bool:
            raise RegistryError("invalid_termination_result")
        with self._transaction() as db:
            attempt = self._by_id(db, attempt_id)
            self._version(attempt, expected_version)
            if attempt.state not in {"terminating", "termination_unknown"}:
                raise RegistryError("invalid_transition")
            db.execute("UPDATE attempts SET state=?,version=version+1,updated_at=? WHERE id=?",
                       ("terminated" if confirmed else "termination_unknown", self._clock(), attempt.id))
            return self._by_id(db, attempt.id)

    def revoke(self, grant_id: str) -> None:
        with self._transaction() as db:
            db.execute("INSERT INTO revocations VALUES (?,?) ON CONFLICT(grant_id) DO NOTHING", (grant_id, self._clock()))
            row = db.execute("SELECT * FROM attempts WHERE grant_id=?", (grant_id,)).fetchone()
            if row:
                self._terminate(db, Attempt(**dict(row)))

    def expire_due(self) -> int:
        with self._transaction() as db:
            now = self._clock()
            return db.execute("""UPDATE attempts SET state='terminating',version=version+1,updated_at=?
                WHERE deadline<=? AND state NOT IN ('terminating','termination_unknown','terminated')""", (now, now)).rowcount

    def unterminated(self, *, limit: int = 100, after_id: str = "") -> list[Attempt]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise RegistryError("invalid_page_size")
        with self._connection() as db:
            return [Attempt(**dict(row)) for row in db.execute(
                "SELECT * FROM attempts WHERE state!='terminated' AND id>? ORDER BY id LIMIT ?", (after_id, limit))]

    def find(self, attempt_id: str) -> Attempt | None:
        """Trusted administrative lookup; does not authorize a workload operation."""
        with self._connection() as db:
            row = db.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
            return Attempt(**dict(row)) if row else None

    def find_grant(self, grant_id: str) -> Attempt | None:
        with self._connection() as db:
            row = db.execute("SELECT * FROM attempts WHERE grant_id=?", (grant_id,)).fetchone()
            return Attempt(**dict(row)) if row else None

    def has_pending_termination(self) -> bool:
        with self._connection() as db:
            return db.execute("SELECT 1 FROM attempts WHERE state IN ('terminating','termination_unknown') LIMIT 1").fetchone() is not None

    def observe_orphan(self, container_id: str, attempt_id: str) -> Orphan:
        """Persist discovery, not ownership proof. Must precede external removal."""
        if (not isinstance(container_id, str) or not _REVISION.fullmatch(container_id)
                or not isinstance(attempt_id, str) or not re.fullmatch(r"[0-9a-f]{32}", attempt_id)):
            raise RegistryError("invalid_orphan_identity")
        with self._transaction() as db:
            now = self._clock()
            db.execute("INSERT INTO orphans VALUES (?,?,'observed',1,?,?) ON CONFLICT(id) DO NOTHING",
                       (container_id, attempt_id, now, now))
            orphan = Orphan(**dict(db.execute("SELECT * FROM orphans WHERE id=?", (container_id,)).fetchone()))
            if orphan.attempt_id != attempt_id or orphan.state == "terminated":
                raise RegistryError("orphan_identity_conflict")
            return orphan

    def record_orphan_termination(self, container_id: str, expected_version: int, *, confirmed: bool) -> Orphan:
        if type(confirmed) is not bool:
            raise RegistryError("invalid_termination_result")
        with self._transaction() as db:
            row = db.execute("SELECT * FROM orphans WHERE id=?", (container_id,)).fetchone()
            if row is None:
                raise RegistryError("orphan_not_found")
            orphan = Orphan(**dict(row))
            if type(expected_version) is not int or expected_version != orphan.version:
                raise RegistryError("version_conflict")
            if orphan.state == "terminated":
                raise RegistryError("invalid_transition")
            db.execute("UPDATE orphans SET state=?,version=version+1,updated_at=? WHERE id=?",
                       ("terminated" if confirmed else "termination_unknown", self._clock(), container_id))
            return Orphan(**dict(db.execute("SELECT * FROM orphans WHERE id=?", (container_id,)).fetchone()))

    def pending_orphans(self, *, limit: int = 100) -> list[Orphan]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise RegistryError("invalid_page_size")
        with self._connection() as db:
            return [Orphan(**dict(row)) for row in db.execute(
                "SELECT * FROM orphans WHERE state!='terminated' ORDER BY updated_at,id LIMIT ?", (limit,))]
