"""A different unguessable session cookie value on every immutable preview port."""
import re

from .preview_access import PreviewAccessError


def preview_cookie_name(port: int) -> str:
    if type(port) is not int or not 1024 <= port <= 65535:
        raise PreviewAccessError('invalid_preview_port')
    return f'__Host-atom_preview_{port}'


def preview_cookie(headers: list[tuple[bytes, bytes]], *, port: int) -> str | None:
    name = preview_cookie_name(port)
    values = [value for key, value in headers if key.lower() == b'cookie']
    if not values:
        return None
    if len(values) != 1 or not isinstance(values[0], bytes) or len(values[0]) > 8192:
        raise PreviewAccessError('preview_access_denied')
    try:
        raw = values[0].decode('ascii')
    except UnicodeError:
        raise PreviewAccessError('preview_access_denied') from None
    found = []
    for part in raw.split(';'):
        if not part.strip():
            continue
        candidate, separator, value = part.lstrip().partition('=')
        if candidate.strip() == name:
            if not separator or re.fullmatch(r'[0-9a-f]{64}', value) is None:
                raise PreviewAccessError('preview_access_denied')
            found.append(value)
    if len(found) > 1:
        raise PreviewAccessError('preview_access_denied')
    return found[0] if found else None
