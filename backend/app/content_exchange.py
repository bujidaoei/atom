"""Service-owned top-level handoff exchange; never serves project code."""
import base64
from datetime import datetime, timezone
import hashlib
import re

from starlette.responses import Response

from .access_repository import AccessError
from .content_cookies import BOOTSTRAP_COOKIE, CONTENT_COOKIE, bootstrap_cookie

EXCHANGE_PATH = '/_atom/exchange'
SCRIPT = """(async () => {
  const handoff = location.hash.slice(1);
  history.replaceState(null, '', '/_atom/exchange');
  const status = document.getElementById('status');
  if (!/^[0-9a-f]{64}$/.test(handoff)) {
    status.textContent = 'Access link is invalid. Reopen it from Atom.';
    return;
  }
  try {
    const response = await fetch('/_atom/exchange', {
      method: 'POST', mode: 'same-origin', credentials: 'same-origin', redirect: 'error',
      headers: {'Content-Type': 'application/octet-stream'}, body: handoff,
      signal: AbortSignal.timeout(10000)
    });
    if (response.status !== 204) throw new Error('exchange_denied');
    location.replace('/');
  } catch {
    status.textContent = 'Access could not be opened. Return to Atom and try again.';
  }
})();"""
_SCRIPT_HASH = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
EXCHANGE_HEADERS = {
    'Cache-Control': 'no-store',
    'Referrer-Policy': 'no-referrer',
    'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy': (
        "default-src 'none'; script-src 'sha256-" + _SCRIPT_HASH + "'; connect-src 'self'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; worker-src 'none'"
    ),
}
_PAGE = ('<!doctype html><html lang="en"><meta charset="utf-8">'
         '<meta name="viewport" content="width=device-width, initial-scale=1">'
         '<title>Open private project</title><p id="status">Opening private project…</p>'
         '<script>' + SCRIPT + '</script></html>')


class ExchangeRequestError(ValueError):
    def __init__(self, status):
        self.status = status
        super().__init__('invalid_content_exchange')


def _one(headers, name):
    values = [value for key, value in headers if key.lower() == name]
    if len(values) != 1:
        raise ExchangeRequestError(400)
    return values[0]


def validate_exchange(scope, hosts):
    headers = scope.get('headers', [])
    binding = hosts.binding(headers)
    if (scope.get('scheme') != 'https' or scope.get('query_string', b'')
            or scope.get('path') != EXCHANGE_PATH
            or scope.get('raw_path', EXCHANGE_PATH.encode()) != EXCHANGE_PATH.encode()):
        raise ExchangeRequestError(400)
    if scope['method'] == 'POST':
        if _one(headers, b'origin') != hosts.url(binding).rstrip('/').encode('ascii'):
            raise ExchangeRequestError(403)
        if _one(headers, b'content-type') != b'application/octet-stream':
            raise ExchangeRequestError(415)
        if _one(headers, b'content-length') != b'64':
            raise ExchangeRequestError(400)
        if any(key.lower() in (b'content-encoding', b'transfer-encoding') for key, _ in headers):
            raise ExchangeRequestError(400)
        if bootstrap_cookie(headers) is None:
            raise AccessError('content_access_denied')
    elif scope['method'] not in ('GET', 'HEAD'):
        raise ExchangeRequestError(405)
    return binding


async def receive_handoff(receive):
    body = bytearray()
    for _ in range(128):
        event = await receive()
        if event['type'] != 'http.request':
            raise ExchangeRequestError(400)
        chunk = event.get('body', b'')
        if len(body) + len(chunk) > 64:
            raise ExchangeRequestError(413)
        body.extend(chunk)
        if not event.get('more_body', False):
            break
    else:
        raise ExchangeRequestError(400)
    if re.fullmatch(rb'[0-9a-f]{64}', body) is None:
        raise ExchangeRequestError(400)
    return bytes(body).decode('ascii')


def exchange_response(scope, hosts, access, handoff=None):
    binding = validate_exchange(scope, hosts)
    if scope['method'] in ('GET', 'HEAD'):
        return Response(_PAGE, media_type='text/html', headers=EXCHANGE_HEADERS)
    credential = access.exchange(binding_id=binding, handoff=handoff,
                                 browser_nonce=bootstrap_cookie(scope.get('headers', [])))
    response = Response(status_code=204, headers=EXCHANGE_HEADERS)
    response.set_cookie(CONTENT_COOKIE, credential.secret, path='/', secure=True,
                        httponly=True, samesite='lax',
                        expires=datetime.fromtimestamp(credential.expires_at, timezone.utc))
    response.delete_cookie(BOOTSTRAP_COOKIE, path='/', secure=True, httponly=True, samesite='lax')
    return response
