"""Explicit console authentication cutover; no legacy credential fallback."""
import re

from fastapi import HTTPException

from .access_repository import AccessRepository
from .config import get_settings
from .durable_credentials import DurableConsoleCredentials

DURABLE_COOKIE = '__Host-atom_console'


def credentials():
    settings = get_settings()
    return DurableConsoleCredentials(AccessRepository(settings.db_path), key=settings.secret,
                                     issuer='atom-console', audience='atom-console')


def session_cookie_name():
    return DURABLE_COOKIE if get_settings().session_mode == 'durable' else 'atom_session'


def request_session_token(request):
    if get_settings().session_mode != 'durable':
        return request.cookies.get('atom_session')
    headers = request.headers.getlist('cookie')
    if not headers:
        return None
    if len(headers) != 1 or len(headers[0]) > 8192 or not headers[0].isascii():
        raise HTTPException(401, '登录凭据无效')
    values = []
    for part in headers[0].split(';'):
        name, separator, value = part.lstrip().partition('=')
        if name.strip() == DURABLE_COOKIE:
            if (not separator or len(value) > 4096
                    or re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', value) is None):
                raise HTTPException(401, '登录凭据无效')
            values.append(value)
    if len(values) > 1:
        raise HTTPException(401, '登录凭据无效')
    return values[0] if values else None


def require_auth_origin(request):
    settings = get_settings()
    if settings.session_mode != 'durable':
        return
    hosts = request.headers.getlist('host')
    origins = request.headers.getlist('origin')
    if (request.url.scheme != 'https' or len(hosts) != 1
            or hosts[0].lower().removesuffix(':443') != settings.console_origin[8:]
            or origins != [settings.console_origin]):
        raise HTTPException(403, '请求来源无效')
