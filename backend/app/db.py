from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_settings = get_settings()

engine: Engine = create_engine(
    f"sqlite:///{_settings.db_path}",
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _configure_sqlite(dbapi_connection, _record) -> None:
    """Foreign keys are off by default in SQLite, and WAL keeps the SSE readers
    from blocking the orchestrator's writes."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Standalone session for background work that outlives a request."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
