"""Strict content-cookie extraction; console credentials never confer access."""
import re

from .access_repository import AccessError

CONTENT_COOKIE = '__Host-atom_content'
BOOTSTRAP_COOKIE = '__Host-atom_bootstrap'


def content_session_cookie(headers: list[tuple[bytes,bytes]]) -> str | None:
    return _credential_cookie(headers,CONTENT_COOKIE)


def bootstrap_cookie(headers: list[tuple[bytes,bytes]]) -> str | None:
    return _credential_cookie(headers,BOOTSTRAP_COOKIE)


def _credential_cookie(headers,selected_name):
    values=[value for key,value in headers if key.lower()==b'cookie']
    if not values:return None
    if len(values)!=1 or not isinstance(values[0],bytes) or len(values[0])>8192:
        raise AccessError('content_access_denied')
    try:raw=values[0].decode('ascii')
    except UnicodeError:raise AccessError('content_access_denied') from None
    selected=[]
    for part in raw.split(';'):
        if not part.strip():continue
        name,separator,value=part.lstrip().partition('=')
        if name.strip()==selected_name:
            if not separator or re.fullmatch(r'[0-9a-f]{64}',value) is None:
                raise AccessError('content_access_denied')
            selected.append(value)
    if len(selected)>1:raise AccessError('content_access_denied')
    return selected[0] if selected else None
