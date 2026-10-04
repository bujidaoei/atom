"""Public view selectors and canonical resource routing; never authorization."""
import re
from urllib.parse import quote, unquote, urlsplit

from .preview_access import PreviewAccessError

VIEW_PREFIX = '/_atom/view/'
VIEW_ID = re.compile(r'[0-9a-f]{64}\Z')


def view_root(view_id: str) -> str:
    if type(view_id) is not str or VIEW_ID.fullmatch(view_id) is None:
        raise PreviewAccessError('preview_access_denied')
    return f'{VIEW_PREFIX}{view_id}/'


def split_view(path: str) -> tuple[str, str] | None:
    if not path.startswith(VIEW_PREFIX):
        return None
    selector, slash, remainder = path[len(VIEW_PREFIX):].partition('/')
    if not slash or VIEW_ID.fullmatch(selector) is None:
        return None
    return selector, '/' + remainder


def valid_path(scope) -> bool:
    path = scope.get('path', '/')
    if (not path.startswith('/') or len(path) > 4096 or '\\' in path
            or any(ord(c) < 32 or ord(c) == 127 for c in path)
            or any(p in ('.', '..') for p in path.split('/'))):
        return False
    raw = scope.get('raw_path', path.encode())
    try:
        # Encoded separators and double encodings must not select another namespace.
        return (unquote(raw.decode('ascii'), errors='strict') == path
                and not re.search(br'%(?:2f|5c|25|00)', raw, re.I))
    except (UnicodeError, ValueError):
        return False


def root_redirect(scope, origin: str) -> str | None:
    values = [v for k, v in scope.get('headers', []) if k.lower() == b'referer']
    if len(values) != 1 or len(values[0]) > 8192:
        return None
    try:
        url = urlsplit(values[0].decode('ascii'))
        if f'{url.scheme}://{url.netloc}' != origin or url.username or url.password:
            return None
        selected = split_view(unquote(url.path, errors='strict'))
        if selected is None:
            return None
        query = scope.get('query_string', b'').decode('ascii')
        if len(query) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in query):
            return None
        return (view_root(selected[0]) + quote(scope['path'].lstrip('/'), safe='/')
                + ('?' + query if query else ''))
    except (UnicodeError, ValueError):
        return None
