"""Top-level browser bootstrap with a fixed configured console destination."""
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from urllib.parse import urlencode

from starlette.responses import Response

from .content_cookies import BOOTSTRAP_COOKIE
from .content_exchange import ExchangeRequestError, _one
from .content_hosts import ContentHostError, ContentHosts

BOOTSTRAP_PATH = '/_atom/bootstrap'
BOOTSTRAP_HEADERS = {
    'Cache-Control': 'no-store',
    'Referrer-Policy': 'no-referrer',
    'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy': "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
}


@dataclass(frozen=True)
class ContentNavigation:
    console_origin: str
    console_base_path: str = ''

    def __post_init__(self):
        value = self.console_origin
        if not isinstance(value, str) or not value.startswith('https://'):
            raise ValueError('invalid_content_console_origin')
        if (type(self.console_base_path) is not str or len(self.console_base_path) > 160
                or re.fullmatch(r'(?:/[A-Za-z0-9_-]+)*', self.console_base_path) is None):
            raise ValueError('invalid_content_console_path')
        try:
            ContentHosts(value[8:])
        except ContentHostError:
            raise ValueError('invalid_content_console_origin') from None

    def validate_content_hosts(self, hosts):
        console = self.console_origin[8:]
        if (console == hosts.suffix or console.endswith('.' + hosts.suffix)
                or hosts.suffix.endswith('.' + console)):
            raise ValueError('overlapping_content_console_hosts')
        # Separate registrable sites, DNS ownership and TLS still need deployment
        # validation; string comparison is not a public-suffix-list check.


def bootstrap_response(scope, hosts, access, navigation):
    binding = hosts.binding(scope.get('headers', []))
    if scope['method'] != 'GET':
        raise ExchangeRequestError(405, allow='GET')
    if (scope.get('scheme') != 'https' or scope.get('query_string', b'')
            or scope.get('path') != BOOTSTRAP_PATH
            or scope.get('raw_path', BOOTSTRAP_PATH.encode()) != BOOTSTRAP_PATH.encode()):
        raise ExchangeRequestError(400)
    headers = scope.get('headers', [])
    if (_one(headers, b'sec-fetch-mode') != b'navigate'
            or _one(headers, b'sec-fetch-dest') != b'document'):
        raise ExchangeRequestError(403)
    if any(key.lower() in (b'purpose', b'sec-purpose') for key, _ in headers):
        raise ExchangeRequestError(403)
    credential = access.bootstrap(binding_id=binding)
    location = navigation.console_origin + navigation.console_base_path + '/content-access?' + urlencode({
        'binding': binding, 'challenge': credential.challenge,
    })
    response = Response(status_code=303, headers={**BOOTSTRAP_HEADERS, 'Location': location})
    response.set_cookie(BOOTSTRAP_COOKIE, credential.secret, path='/', secure=True,
                        httponly=True, samesite='lax',
                        expires=datetime.fromtimestamp(credential.expires_at, timezone.utc))
    return response
