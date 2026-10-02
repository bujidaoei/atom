"""Explicit console authentication cutover; no legacy credential fallback."""
import base64
import hashlib
import hmac
import re

from fastapi import HTTPException

from .access_repository import AccessError, AccessRepository
from .config import get_settings
from .durable_credentials import DurableConsoleCredentials

DURABLE_COOKIE = '__Host-atom_console'
PROOF_HEADER = 'x-atom-console-proof'
_PROOF_CONTEXT = b'atom-console-origin-proof-v1\0'


def _session_proof(session_id: str) -> str:
    """Derive a distinct browser-held proof from a live persisted session ID.

    The server secret never reaches the browser; the HttpOnly cookie does not
    reveal the session ID to content running on another port of the same IP.
    """
    digest = hmac.new(get_settings().secret.encode('ascii'),
                      _PROOF_CONTEXT + session_id.encode('ascii'), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')


def proof_for_new_session(token: str) -> str:
    source = credentials().authenticate(token)
    if source is None:
        raise AccessError('access_unavailable')
    return _session_proof(source.id)


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
    token = values[0] if values else None
    if token and get_settings().console_proof_required:
        proofs = request.headers.getlist(PROOF_HEADER)
        if len(proofs) != 1 or re.fullmatch(r'[A-Za-z0-9_-]{43}', proofs[0]) is None:
            raise HTTPException(401, '请重新登录')
        source = credentials().authenticate(token)
        if source is None or not hmac.compare_digest(proofs[0], _session_proof(source.id)):
            raise HTTPException(401, '请重新登录')
    return token


def require_console_host(request):
    settings = get_settings()
    hosts = request.headers.getlist('host')
    if (request.url.scheme != 'https' or len(hosts) != 1 or settings.console_origin is None
            or hosts[0].lower().removesuffix(':443') != settings.console_origin[8:]):
        raise HTTPException(403, '请求来源无效')


def require_auth_origin(request):
    settings = get_settings()
    if settings.session_mode != 'durable':
        return
    require_console_host(request)
    if request.headers.getlist('origin') != [settings.console_origin]:
        raise HTTPException(403, '请求来源无效')


def require_authenticated_console_request(request):
    """Keep cookie-authenticated API authority on the configured console origin."""
    if get_settings().session_mode != 'durable':
        return
    require_console_host(request)
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        require_auth_origin(request)
