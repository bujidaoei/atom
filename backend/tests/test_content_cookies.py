import pytest

from app.access_repository import AccessError
from app.content_cookies import CONTENT_COOKIE,content_session_cookie


def test_only_dedicated_cookie_is_selected():
    assert content_session_cookie([]) is None
    assert content_session_cookie([(b'cookie',b'atom_session=console; generated=other')]) is None
    assert content_session_cookie([(b'Cookie',f'generated=value; {CONTENT_COOKIE}={"a"*64};'.encode())])=='a'*64


@pytest.mark.parametrize('value',['','a'*63,'A'*64,'"'+'a'*64+'"','a'*64+' ', 'a'*64+'=extra','../secret'])
def test_malformed_session_is_not_repaired(value):
    with pytest.raises(AccessError):content_session_cookie([(b'cookie',f'{CONTENT_COOKIE}={value};'.encode())])


def test_ambiguous_oversized_or_non_ascii_cookie_is_denied():
    token=f'{CONTENT_COOKIE}={"a"*64}'.encode()
    for headers in ([(b'cookie',token+b'; '+token)],[(b'cookie',token),(b'Cookie',token)],
        [(b'cookie',b'x'*8193)],[(b'cookie',b'\xff')],[(b'cookie',CONTENT_COOKIE.encode())]):
        with pytest.raises(AccessError):content_session_cookie(headers)
