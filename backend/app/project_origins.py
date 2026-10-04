"""Durable, never-reused browser origins for IP-only project delivery."""
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time

from .migrations import MigrationError, _schema, verify


class ProjectOriginError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProjectOrigins:
    project_id: str
    preview_port: int
    public_port: int


@dataclass(frozen=True)
class OriginRoute:
    project_id: str
    purpose: str
    port: int


class ProjectOriginRepository:
    def __init__(self, path: Path, *, first_port: int, last_port: int, lock_timeout: float = 3):
        if (type(first_port) is not int or type(last_port) is not int
                or not 1024 <= first_port < last_port <= 65535
                or last_port - first_port + 1 > 512
                or isinstance(lock_timeout, bool) or not isinstance(lock_timeout, (int, float))
                or not 0 < lock_timeout <= 10):
            raise ProjectOriginError('invalid_origin_configuration')
        self.path = Path(path)
        self.first_port, self.last_port, self.timeout = first_port, last_port, lock_timeout
        try:
            if verify(self.path) not in (17, 18, 19):
                raise ProjectOriginError('origin_schema_required')
        except MigrationError:
            raise ProjectOriginError('origin_schema_required') from None
        try:
            with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True,
                                         timeout=self.timeout)) as db:
                if db.execute('SELECT 1 FROM project_origin_ports WHERE port<? OR port>? LIMIT 1',
                              (first_port, last_port)).fetchone() is not None:
                    raise ProjectOriginError('origin_range_changed')
        except (sqlite3.Error, OSError):
            raise ProjectOriginError('origin_unavailable') from None

    @contextmanager
    def _database(self, *, write: bool):
        db = None
        try:
            db = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True,
                                 isolation_level=None, timeout=self.timeout)
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            if _schema(db) not in (17, 18, 19):
                raise ProjectOriginError('origin_schema_required')
            yield db
            db.execute('COMMIT')
        except sqlite3.IntegrityError:
            raise ProjectOriginError('origin_conflict') from None
        except (sqlite3.Error, OSError, MigrationError):
            raise ProjectOriginError('origin_unavailable') from None
        finally:
            if db is not None:
                if db.in_transaction:
                    db.rollback()
                db.close()

    def reserve(self, project_id: str) -> ProjectOrigins:
        if not isinstance(project_id, str) or not project_id or len(project_id) > 100:
            raise ProjectOriginError('invalid_origin_project')
        with self._database(write=True) as db:
            return self._reserve_in_db(db, project_id)

    def reserve_in_transaction(self, db: sqlite3.Connection, project_id: str) -> ProjectOrigins:
        """Join project insertion and port reservation in the caller's transaction."""
        if (not isinstance(db, sqlite3.Connection) or not db.in_transaction
                or not isinstance(project_id, str) or not project_id or len(project_id) > 100):
            raise ProjectOriginError('invalid_origin_transaction')
        try:
            if _schema(db) not in (17, 18, 19):
                raise ProjectOriginError('origin_schema_required')
            return self._reserve_in_db(db, project_id)
        except sqlite3.IntegrityError:
            raise ProjectOriginError('origin_conflict') from None
        except sqlite3.Error:
            raise ProjectOriginError('origin_unavailable') from None

    def _reserve_in_db(self, db: sqlite3.Connection, project_id: str) -> ProjectOrigins:
        if db.execute('SELECT 1 FROM project_origin_ports WHERE port<? OR port>? LIMIT 1',
                      (self.first_port, self.last_port)).fetchone() is not None:
            raise ProjectOriginError('origin_range_changed')
        rows = db.execute('SELECT purpose,port FROM project_origin_ports WHERE project_id=?',
                          (project_id,)).fetchall()
        if rows:
            ports = dict(rows)
            if len(rows) != 2 or set(ports) != {'preview', 'public'}:
                raise ProjectOriginError('origin_incomplete')
            return ProjectOrigins(project_id, ports['preview'], ports['public'])
        if db.execute('SELECT 1 FROM projects WHERE id=?', (project_id,)).fetchone() is None:
            raise ProjectOriginError('origin_project_missing')
        occupied = {row[0] for row in db.execute(
            'SELECT port FROM project_origin_ports WHERE port BETWEEN ? AND ?',
            (self.first_port, self.last_port))}
        available = (port for port in range(self.first_port, self.last_port + 1)
                     if port not in occupied)
        preview = next(available, None)
        public = next(available, None)
        if public is None:
            raise ProjectOriginError('origin_capacity')
        now = int(time.time())
        if not 0 <= now < 2**63:
            raise ProjectOriginError('origin_clock_invalid')
        db.executemany('INSERT INTO project_origin_ports VALUES (?,?,?,?)',
                       [(project_id, 'preview', preview, now),
                        (project_id, 'public', public, now)])
        return ProjectOrigins(project_id, preview, public)

    def reserve_existing(self) -> tuple[ProjectOrigins, ...]:
        """Allocate every existing project as one migration transaction.

        A failed preflight leaves no partial origin assignments. Retired ports
        remain occupied even though their projects no longer exist.
        """
        with self._database(write=True) as db:
            if db.execute('SELECT 1 FROM project_origin_ports WHERE port<? OR port>? LIMIT 1',
                          (self.first_port, self.last_port)).fetchone() is not None:
                raise ProjectOriginError('origin_range_changed')
            projects = [row[0] for row in db.execute('SELECT id FROM projects ORDER BY id LIMIT 257')]
            if len(projects) > 256:
                raise ProjectOriginError('origin_capacity')
            occupied = {row[0] for row in db.execute('SELECT port FROM project_origin_ports')}
            rows = db.execute('SELECT project_id,purpose,port FROM project_origin_ports').fetchall()
            existing = {}
            for project_id, purpose, port in rows:
                existing.setdefault(project_id, {})[purpose] = port
            available = (port for port in range(self.first_port, self.last_port + 1)
                         if port not in occupied)
            assigned, additions = [], []
            now = int(time.time())
            if not 0 <= now < 2**63:
                raise ProjectOriginError('origin_clock_invalid')
            for project_id in projects:
                if project_id in existing:
                    ports = existing[project_id]
                    if len(ports) != 2 or set(ports) != {'preview', 'public'}:
                        raise ProjectOriginError('origin_incomplete')
                    assigned.append(ProjectOrigins(project_id, ports['preview'], ports['public']))
                else:
                    preview = next(available, None)
                    public = next(available, None)
                    if public is None:
                        raise ProjectOriginError('origin_capacity')
                    additions.extend(((project_id, 'preview', preview, now),
                                      (project_id, 'public', public, now)))
                    assigned.append(ProjectOrigins(project_id, preview, public))
            db.executemany('INSERT INTO project_origin_ports VALUES (?,?,?,?)', additions)
            return tuple(assigned)

    def route(self, port: int) -> OriginRoute | None:
        if type(port) is not int or not self.first_port <= port <= self.last_port:
            raise ProjectOriginError('invalid_origin_port')
        with self._database(write=False) as db:
            row = db.execute('SELECT o.project_id,o.purpose,o.port FROM project_origin_ports o '
                             'JOIN projects p ON p.id=o.project_id WHERE o.port=?', (port,)).fetchone()
            return OriginRoute(*row) if row else None

    def for_project(self, project_id: str) -> ProjectOrigins | None:
        if not isinstance(project_id, str) or not project_id or len(project_id) > 100:
            raise ProjectOriginError('invalid_origin_project')
        with self._database(write=False) as db:
            rows = db.execute('SELECT purpose,port FROM project_origin_ports '
                              'WHERE project_id=?', (project_id,)).fetchall()
            if not rows:
                return None
            ports = dict(rows)
            if len(rows) != 2 or set(ports) != {'preview', 'public'}:
                raise ProjectOriginError('origin_incomplete')
            return ProjectOrigins(project_id, ports['preview'], ports['public'])

    def active_routes(self) -> tuple[OriginRoute, ...]:
        with self._database(write=False) as db:
            if db.execute('SELECT 1 FROM project_origin_ports WHERE port<? OR port>? LIMIT 1',
                          (self.first_port, self.last_port)).fetchone() is not None:
                raise ProjectOriginError('origin_range_changed')
            rows = db.execute('SELECT o.project_id,o.purpose,o.port FROM project_origin_ports o '
                              'JOIN projects p ON p.id=o.project_id ORDER BY o.port').fetchall()
            return tuple(OriginRoute(*row) for row in rows)
