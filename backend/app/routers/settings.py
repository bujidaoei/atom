from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..config import get_settings
from ..deps import CurrentUser, DbSession
from ..masking import mask_secret
from ..models import UserSettings
from ..services.gateway import list_models
from ..services.provider_connection import (
    ProviderConfigurationError, normalize_endpoint, resolve_provider, validate_key,
)

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

    model = overrides.model or defaults.llm_model
    try:
        connection = resolve_provider(defaults, overrides)
    except ProviderConfigurationError as error:
        return {
            "baseUrl": overrides.base_url or defaults.llm_base_url,
            "model": model,
            "apiKeyMasked": "",
            "hasUserKey": bool(overrides.api_key),
            "source": "unconfigured",
            "models": [],
            "modelsStatus": "unconfigured",
            "configurationError": error.detail,
        }
    models = await list_models(connection.base_url, connection.api_key)
    return {
        "baseUrl": connection.base_url,
        "model": model,
        "apiKeyMasked": mask_secret(connection.api_key),
        "hasUserKey": bool(overrides.api_key),
        "source": connection.source,
        "models": [{"id": item} for item in models],
        "modelsStatus": "available" if models else "unavailable",
        "configurationError": None,
    }


@router.get("")
async def read(user: CurrentUser, session: DbSession) -> dict[str, object]:
    payload = await _payload(session, user.id)
    session.commit()
    return payload


@router.put("")
async def update(body: SettingsPatch, user: CurrentUser, session: DbSession) -> dict[str, object]:
    overrides = _overrides(session, user.id)
    defaults = get_settings()
    previous_endpoint = overrides.base_url or defaults.llm_base_url
    endpoint = previous_endpoint
    if body.baseUrl is not None:
        endpoint = body.baseUrl if body.baseUrl else defaults.llm_base_url
    endpoint = normalize_endpoint(endpoint)
    key = overrides.api_key
    supplied_key = False
    if body.apiKey is not None:
        if any(ord(c) < 32 or ord(c) == 127 for c in body.apiKey):
            raise ProviderConfigurationError("API Key 不能包含控制字符")
        candidate = body.apiKey.strip()
        if candidate and candidate != mask_secret(key or ""):
            if "*" in candidate:
                raise ProviderConfigurationError("请填写完整 API Key，不能使用打码值绑定新地址")
            key = validate_key(candidate)
            supplied_key = True
        elif not candidate:
            key = None
    if key and not supplied_key:
        if not overrides.base_url:
            raise ProviderConfigurationError("个人 Key 尚未绑定地址，请重新填写 API Key 后保存")
        try:
            unchanged = endpoint == normalize_endpoint(previous_endpoint)
        except ProviderConfigurationError:
            unchanged = False
        if not unchanged:
            raise ProviderConfigurationError("更换 Base URL 时请同时重新填写该服务的 API Key")
    # Pin personal credentials even when they use the current managed endpoint.
    # Later administrator endpoint changes must not redirect a personal secret.
    overrides.base_url = endpoint if key or endpoint != normalize_endpoint(defaults.llm_base_url) else None
    overrides.api_key = key
    resolve_provider(defaults, overrides)
    if body.model is not None:
        overrides.model = body.model.strip() or None

    session.commit()
    return await _payload(session, user.id)


@router.delete("/api-key")
async def clear_key(user: CurrentUser, session: DbSession) -> dict[str, object]:
    overrides = _overrides(session, user.id)
    overrides.api_key = None
    overrides.base_url = None
    session.commit()
    return await _payload(session, user.id)
