from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from .db import session_scope
from .models import Project, RunEvent

# Events are durable, so a reconnecting client can replay. This cap keeps a
# long-running project's table from growing without bound; the UI only ever
# needs the recent tail plus whatever arrives live.
_RETAINED_EVENTS_PER_PROJECT = 4000
_TRIM_EVERY = 500


@dataclass(frozen=True)
class Event:
    seq: int
    run_id: str | None
    role: str | None
    type: str
    payload: dict[str, Any]
    at: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "seq": self.seq,
                "runId": self.run_id,
                "role": self.role,
                "type": self.type,
                "payload": self.payload,
                "at": self.at,
            },
            ensure_ascii=False,
        )


class EventBus:
    """Per-project fan-out over in-process asyncio queues.

    Durability lives in SQLite; this class only handles live delivery to the
    SSE handlers attached right now. A single-box deployment makes that enough,
    and it keeps the read path off the database on every token.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[Event]]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._writes_since_trim = 0
        self._publish_lock = asyncio.Lock()

    async def subscribe(self, project_id: str) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=1000)
        async with self._lock:
            self._subscribers[project_id].add(queue)
        return queue

    async def unsubscribe(self, project_id: str, queue: asyncio.Queue[Event]) -> None:
        async with self._lock:
            listeners = self._subscribers.get(project_id)
            if not listeners:
                return
            listeners.discard(queue)
            if not listeners:
                self._subscribers.pop(project_id, None)

    async def publish(
        self,
        project_id: str,
        type_: str,
        payload: dict[str, Any],
        *,
        run_id: str | None = None,
        role: str | None = None,
    ) -> Event:
        # Commit and delivery share one ordering boundary in this single worker.
        # Keep the short DB write synchronous: cancellation must not leave a
        # detached writer allocating a sequence after releasing the lock.
        async with self._publish_lock:
            event = self._persist(project_id, type_, payload, run_id, role)
            for queue in list(self._subscribers.get(project_id, ())):
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    while not queue.empty():
                        queue.get_nowait()
                    queue.put_nowait(
                        Event(0, None, None, "stream.resync", {}, event.at)
                    )
                    self._subscribers[project_id].discard(queue)
            return event

    def _persist(
        self,
        project_id: str,
        type_: str,
        payload: dict[str, Any],
        run_id: str | None,
        role: str | None,
    ) -> Event:
        with session_scope() as session:
            project = session.get(Project, project_id, with_for_update=False)
            seq = (project.event_seq if project else 0) + 1
            if project:
                project.event_seq = seq
            session.add(
                RunEvent(
                    project_id=project_id,
                    seq=seq,
                    run_id=run_id,
                    role=role,
                    type=type_,
                    payload_json=json.dumps(payload, ensure_ascii=False),
                )
            )
        self._writes_since_trim += 1
        if self._writes_since_trim >= _TRIM_EVERY:
            self._writes_since_trim = 0
            self._trim(project_id)
        return Event(
            seq=seq,
            run_id=run_id,
            role=role,
            type=type_,
            payload=payload,
            at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _trim(project_id: str) -> None:
        with session_scope() as session:
            cutoff = session.scalar(
                select(RunEvent.seq)
                .where(RunEvent.project_id == project_id)
                .order_by(RunEvent.seq.desc())
                .offset(_RETAINED_EVENTS_PER_PROJECT)
                .limit(1)
            )
            if cutoff is None:
                return
            for stale in session.scalars(
                select(RunEvent).where(
                    RunEvent.project_id == project_id, RunEvent.seq <= cutoff
                )
            ):
                session.delete(stale)

    @staticmethod
    def replay(project_id: str, after: int) -> list[Event]:
        with session_scope() as session:
            rows = session.scalars(
                select(RunEvent)
                .where(RunEvent.project_id == project_id, RunEvent.seq > after)
                .order_by(RunEvent.seq)
                .limit(_RETAINED_EVENTS_PER_PROJECT)
            ).all()
            return [
                Event(
                    seq=row.seq,
                    run_id=row.run_id,
                    role=row.role,
                    type=row.type,
                    payload=json.loads(row.payload_json),
                    at=row.created_at.isoformat(),
                )
                for row in rows
            ]


bus = EventBus()
