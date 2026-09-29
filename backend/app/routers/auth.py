from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from ..config import get_settings
from ..deps import CurrentUser, DbSession, SESSION_COOKIE
from ..models import User, UserSettings
from ..security import hash_password, issue_session, verify_password
from ..serialize import user_json

router = APIRouter(prefix="/auth", tags=["auth"])


class LookupRequest(BaseModel):
    email: EmailStr


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    name: str | None = Field(default=None, max_length=120)


def _find(session, email: str) -> User | None:
    return session.scalars(
        select(User).where(func.lower(User.email) == email.strip().lower())
    ).first()


def _set_cookie(response: Response, user_id: str) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        issue_session(user_id),
        max_age=settings.session_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=settings.cookie_path,
    )


@router.post("/lookup")
def lookup(body: LookupRequest, session: DbSession) -> dict[str, object]:
    """Atoms asks for the email first and branches on whether it exists.

    This deliberately reveals registration status, matching the product being
    cloned. A real deployment would rate-limit this endpoint.
    """
    email = body.email.strip().lower()
    return {"email": email, "exists": _find(session, email) is not None}


@router.post("/register")
def register(body: Credentials, response: Response, session: DbSession) -> dict[str, object]:
    if body.password.isdigit():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "密码不能是纯数字")
    email = body.email.strip().lower()
    if _find(session, email) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该邮箱已注册")

    user = User(
        email=email,
        name=(body.name or email.split("@")[0])[:120],
        password_hash=hash_password(body.password),
        credits=get_settings().starting_credits,
    )
    session.add(user)
    session.flush()
    session.add(UserSettings(user_id=user.id))
    session.commit()

    _set_cookie(response, user.id)
    return user_json(user)


@router.post("/login")
def login(body: Credentials, response: Response, session: DbSession) -> dict[str, object]:
    user = _find(session, body.email)
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "邮箱或密码不正确")
    _set_cookie(response, user.id)
    return user_json(user)


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(SESSION_COOKIE, path=get_settings().cookie_path)
    return {"ok": True}


@router.get("/me")
def me(user: CurrentUser) -> dict[str, object]:
    return user_json(user)
