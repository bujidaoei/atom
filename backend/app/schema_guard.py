from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from .models import Base


class SchemaDrift(RuntimeError):
    """The database on disk does not match the models this build expects."""


def verify(engine: Engine) -> None:
    """Fail fast when an existing database predates the current models.

    ``create_all`` only creates missing tables; it never adds a column to one
    that already exists. Without this check a stale file turns into a stream
    of 500s at request time, which is much harder to diagnose than refusing
    to start.
    """
    inspector = inspect(engine)
    present = set(inspector.get_table_names())
    problems: list[str] = []

    for name, table in Base.metadata.tables.items():
        if name not in present:
            continue
        actual = {column["name"] for column in inspector.get_columns(name)}
        missing = {column.name for column in table.columns} - actual
        if missing:
            problems.append(f"{name}: 缺少字段 {', '.join(sorted(missing))}")

    if problems:
        raise SchemaDrift(
            "数据库结构与当前版本不一致：\n  "
            + "\n  ".join(problems)
            + "\n\n这个 Demo 不带迁移工具。开发环境直接删掉 ATOM_DB_PATH 指向的文件重来；"
            "生产环境请先备份，再手工补上缺失字段。"
        )
