from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User
from app.security import create_token, read_token

COOKIE = "atom_session"


def set_session_cookie(response: Response, user_id: str) -> None:
    response.set_cookie(
        COOKIE,
        create_token(user_id),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=14 * 24 * 3600,
        path=settings.cookie_path or "/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path=settings.cookie_path or "/")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE)
    user_id = read_token(token) if token else None
    user = db.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


def owned_project(db: Session, user: User, project_id: str):
    from app.models import Project

    project = db.scalar(select(Project).where(Project.id == project_id, Project.user_id == user.id))
    if project is None:
        raise HTTPException(status_code=404, detail="没有这个项目")
    return project
