from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import clear_session_cookie, current_user, set_session_cookie
from app.models import User
from app.schemas import LoginIn, RegisterIn, UserOut
from app.security import hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _out(user: User) -> UserOut:
    return UserOut(id=user.id, name=user.name, email=user.email)


@router.post("/register", response_model=UserOut)
def register(body: RegisterIn, response: Response, db: Session = Depends(get_db)) -> UserOut:
    email = body.email.lower()
    exists = db.scalar(select(User).where(User.email == email))
    if exists is not None:
        raise HTTPException(status_code=409, detail="这个邮箱已经注册过")
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    set_session_cookie(response, user.id)
    return _out(user)


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)) -> UserOut:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码不对")
    set_session_cookie(response, user.id)
    return _out(user)


@router.post("/logout")
def logout(response: Response) -> dict:
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return _out(user)
