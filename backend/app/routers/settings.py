from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import CURATED_MODELS, settings
from app.db import get_db
from app.deps import current_user
from app.masking import mask_secret
from app.models import User, UserSettings
from app.schemas import SettingsIn

router = APIRouter(prefix="/settings", tags=["settings"])


def _row(db: Session, user: User) -> UserSettings:
    row = db.get(UserSettings, user.id)
    if row is None:
        row = UserSettings(user_id=user.id, base_url="", api_key="", model="")
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _view(row: UserSettings) -> dict:
    user_key = (row.api_key or "").strip()
    server_key = (settings.llm_api_key or "").strip()
    if user_key:
        source = "user"
        effective = user_key
    elif server_key:
        source = "server"
        effective = server_key
    else:
        source = "none"
        effective = ""
    return {
        "base_url": (row.base_url or "").strip() or settings.llm_base_url,
        "base_url_source": "user" if (row.base_url or "").strip() else "server",
        "model": (row.model or "").strip() or settings.llm_model,
        "model_source": "user" if (row.model or "").strip() else "server",
        "api_key_masked": mask_secret(effective),
        "api_key_source": source,
        "configured": bool(effective),
        "models": CURATED_MODELS,
    }


@router.get("")
def read_settings(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return _view(_row(db, user))


@router.put("")
def update_settings(
    body: SettingsIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    row = _row(db, user)
    if body.base_url is not None:
        value = body.base_url.strip().rstrip("/")
        if value and not value.startswith("https://"):
            raise HTTPException(status_code=422, detail="模型地址需要以 https:// 开头")
        row.base_url = value[:300]
    if body.api_key is not None:
        key = body.api_key.strip()
        if key and (len(key) < 8 or len(key) > 200 or any(char.isspace() for char in key)):
            raise HTTPException(status_code=422, detail="API Key 格式不对")
        row.api_key = key
    if body.model is not None:
        model = body.model.strip()
        if model and (len(model) > 80 or any(char.isspace() for char in model)):
            raise HTTPException(status_code=422, detail="模型名称不对")
        row.model = model
    db.commit()
    return _view(row)


@router.delete("/api-key")
def clear_api_key(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    row = _row(db, user)
    row.api_key = ""
    db.commit()
    return _view(row)
