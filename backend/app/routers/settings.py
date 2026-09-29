from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ..config import get_settings
from ..deps import CurrentUser, DbSession
from ..masking import mask_secret
from ..models import UserSettings
from ..services.gateway import list_models

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsPatch(BaseModel):
    baseUrl: str | None = Field(default=None, max_length=500)
    apiKey: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)


def _overrides(session, user_id: str) -> UserSettings:
    overrides = session.get(UserSettings, user_id)
    if overrides is None:
        overrides = UserSettings(user_id=user_id)
        session.add(overrides)
        session.flush()
    return overrides


async def _payload(session, user_id: str) -> dict[str, object]:
    defaults = get_settings()
    overrides = _overrides(session, user_id)

    base_url = overrides.base_url or defaults.llm_base_url
    api_key = overrides.api_key or defaults.llm_api_key
    model = overrides.model or defaults.llm_model

    return {
        "baseUrl": base_url,
        "model": model,
        "apiKeyMasked": mask_secret(api_key),
        "hasUserKey": bool(overrides.api_key),
        "source": "user" if overrides.api_key else "server",
        "models": [{"id": item} for item in await list_models(base_url, api_key)],
    }


@router.get("")
async def read(user: CurrentUser, session: DbSession) -> dict[str, object]:
    payload = await _payload(session, user.id)
    session.commit()
    return payload


@router.put("")
async def update(body: SettingsPatch, user: CurrentUser, session: DbSession) -> dict[str, object]:
    overrides = _overrides(session, user.id)

    if body.baseUrl is not None:
        candidate = body.baseUrl.strip().rstrip("/")
        if candidate and not candidate.startswith(("http://", "https://")):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Base URL 必须以 http:// 或 https:// 开头")
        overrides.base_url = candidate or None

    if body.apiKey is not None:
        candidate = body.apiKey.strip()
        # The UI shows a masked key; if it comes back unchanged, the user did
        # not retype it and we must not overwrite the stored value.
        if candidate and "*" not in candidate:
            overrides.api_key = candidate
        elif not candidate:
            overrides.api_key = None

    if body.model is not None:
        overrides.model = body.model.strip() or None

    session.commit()
    return await _payload(session, user.id)


@router.delete("/api-key")
async def clear_key(user: CurrentUser, session: DbSession) -> dict[str, object]:
    _overrides(session, user.id).api_key = None
    session.commit()
    return await _payload(session, user.id)
