from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(256))
    credits: Mapped[int] = mapped_column(Integer, default=200)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    settings: Mapped["UserSettings | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    base_url: Mapped[str | None] = mapped_column(String(500))
    api_key: Mapped[str | None] = mapped_column(String(500))
    model: Mapped[str | None] = mapped_column(String(200))

    user: Mapped[User] = relationship(back_populates="settings")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    prompt: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    slug: Mapped[str | None] = mapped_column(String(80), unique=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_run_id: Mapped[str | None] = mapped_column(String(32))
    event_seq: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="projects")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Message.created_at"
    )
    requirements: Mapped[list["Requirement"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Requirement.position"
    )
    runs: Mapped[list["Run"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text, default="")
    run_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="messages")


class Requirement(Base):
    __tablename__ = "requirements"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text, default="")
    checks_json: Mapped[str] = mapped_column(Text, default="[]")
    position: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped[Project] = relationship(back_populates="requirements")

    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_requirement_key"),)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(200))
    phase: Mapped[str] = mapped_column(String(20), default="plan")
    status: Mapped[str] = mapped_column(String(20), default="running")
    heat_id: Mapped[str | None] = mapped_column(String(32), index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship(back_populates="runs")


class RunEvent(Base):
    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("projects.id", ondelete="CASCADE")
    )
    seq: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[str | None] = mapped_column(String(20))
    type: Mapped[str] = mapped_column(String(60))
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_run_events_project_seq", "project_id", "seq"),)


class AcceptanceRun(Base):
    __tablename__ = "acceptance_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    passed: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    results_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Race(Base):
    __tablename__ = "races"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="running")
    winner_heat_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    heats: Mapped[list["RaceHeat"]] = relationship(
        back_populates="race", cascade="all, delete-orphan", order_by="RaceHeat.position"
    )


class RaceHeat(Base):
    __tablename__ = "race_heats"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    race_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("races.id", ondelete="CASCADE"), index=True
    )
    model: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    run_id: Mapped[str | None] = mapped_column(String(32))
    position: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)

    race: Mapped[Race] = relationship(back_populates="heats")


class CreditEntry(Base):
    __tablename__ = "credit_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(40))
    run_id: Mapped[str | None] = mapped_column(String(32))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Publication(Base):
    __tablename__ = "publications"

    slug: Mapped[str] = mapped_column(String(80), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    live: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
