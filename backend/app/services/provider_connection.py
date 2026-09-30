"""Resolve provider endpoints and credentials as one authorization boundary."""
from __future__ import annotations

from dataclasses import dataclass, field
from ipaddress import IPv6Address
import re
from urllib.parse import urlsplit, urlunsplit

from ..config import Settings
from ..errors import AtomError
from ..models import UserSettings


class ProviderConfigurationError(AtomError):
    pass


@dataclass(frozen=True)
class ResolvedProvider:
    base_url: str
    api_key: str = field(repr=False)
    source: str


def normalize_endpoint(value: str) -> str:
    candidate = value.strip()
    invalid = ProviderConfigurationError("Base URL 必须是完整的 HTTP(S) 地址，不能含账号、查询参数、片段或歧义路径")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise invalid
    if not candidate or any(c.isspace() for c in candidate):
        raise invalid
    if any(c in candidate for c in ("\\", "%", "?", "#")):
        raise invalid
    try:
        parts = urlsplit(candidate)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
        ):
            raise invalid
        if any(segment in {".", ".."} for segment in parts.path.split("/")):
            raise invalid
        host = parts.hostname.encode("idna").decode("ascii").lower()
        if parts.netloc.endswith(":"):
            raise invalid
        port = parts.port
        if port is not None and not 1 <= port <= 65535:
            raise invalid
        if ":" in host:
            host = f"[{IPv6Address(host).compressed}]"
        elif not all(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in host.rstrip(".").split(".")
        ):
            raise invalid
        if port is not None and port != (443 if parts.scheme == "https" else 80):
            host = f"{host}:{port}"
        return urlunsplit((parts.scheme, host, parts.path.rstrip("/"), "", ""))
    except (ValueError, UnicodeError):
        raise invalid from None


def validate_key(key: str) -> str:
    if not key or any(c.isspace() or not 32 <= ord(c) < 127 for c in key):
        raise ProviderConfigurationError("请配置有效的 API Key，不能包含空白或控制字符")
    return key


def resolve_provider(settings: Settings, overrides: UserSettings | None) -> ResolvedProvider:
    endpoint = overrides.base_url if overrides else None
    key = overrides.api_key if overrides else None
    if key:
        if not endpoint:
            raise ProviderConfigurationError("个人 Key 尚未绑定服务地址，请重新保存 Base URL 和 API Key")
        return ResolvedProvider(normalize_endpoint(endpoint), validate_key(key), "user")
    default = normalize_endpoint(settings.llm_base_url)
    if endpoint and normalize_endpoint(endpoint) != default:
        raise ProviderConfigurationError("自定义 Base URL 必须配置自己的 API Key，或恢复服务端默认连接")
    return ResolvedProvider(default, validate_key(settings.llm_api_key), "server")
