from __future__ import annotations

from typing import Annotated

from fastapi import Request, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from .db import get_db
from .models import Project, User
from .security import read_session
from .console_auth import request_session_token, require_authenticated_console_request

SESSION_COOKIE = "atom_session"


def current_user(
    session: Annotated[Session, Depends(get_db)],
    request: Request,
) -> User:
    require_authenticated_console_request(request)
    atom_session = request_session_token(request)
    if not atom_session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "请先登录")
    user_id = read_session(atom_session)
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录状态已失效")
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录状态已失效")
    return user


def optional_user(
    session: Annotated[Session, Depends(get_db)],
    request: Request,
) -> User | None:
    require_authenticated_console_request(request)
    atom_session = request_session_token(request)
    if not atom_session:
        return None
    user_id = read_session(atom_session)
    return session.get(User, user_id) if user_id else None


def owned_project(
    project_id: Annotated[str, Path(alias="project_id")],
    session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在")
    return project


CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]
DbSession = Annotated[Session, Depends(get_db)]
OwnedProject = Annotated[Project, Depends(owned_project)]
