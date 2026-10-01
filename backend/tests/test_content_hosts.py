import pytest

from app.content_hosts import ContentHostError, ContentHosts


def test_canonical_host_roundtrip_and_forwarded_host_is_not_authority():
    hosts = ContentHosts('content.example.test')
    identity = 'a'*32
    host = hosts.hostname(identity)
    assert hosts.url(identity) == 'https://'+host+'/'
    assert hosts.binding([(b'Host',host.upper().encode())]) == identity
    assert hosts.binding([(b'host',(host+':443').encode()),(b'x-forwarded-host',b'attacker.test')]) == identity
    with pytest.raises(ContentHostError): hosts.binding([(b'x-forwarded-host',host.encode())])


@pytest.mark.parametrize('suffix',['https://content.test','Content.test','content.test.','content..test',
    '*.content.test','localhost','127.0.0.1','-content.test','content-.test','content.test:443',
    'content.test/path','内容.test','a'*64+'.test'])
def test_configuration_rejects_ambiguous_suffix(suffix):
    with pytest.raises(ContentHostError):ContentHosts(suffix)


@pytest.mark.parametrize('template',['{host}.attacker.test','attacker-{host}','{host}.',' {host}',
    '{host} ','{host}:80','{host}:0443','https://{host}','user@{host}','{host}/',
    '{host},attacker.test','{host}\r\nx: y','{host}%00','r-other.content.test'])
def test_malformed_authority_is_denied(template):
    hosts=ContentHosts('content.test')
    with pytest.raises(ContentHostError):hosts.binding([(b'host',template.format(host=hosts.hostname('a'*32)).encode())])


def test_duplicate_missing_and_non_ascii_hosts_are_denied():
    hosts=ContentHosts('content.test')
    host=hosts.hostname('a'*32).encode()
    for headers in [[],[(b'host',host),(b'Host',host)],[(b'host',b'\xff')]]:
        with pytest.raises(ContentHostError):hosts.binding(headers)


@pytest.mark.parametrize('identity',['a'*31,'A'*32,'../content','a'*33,None])
def test_invalid_binding_cannot_form_url(identity):
    with pytest.raises(ContentHostError):ContentHosts('content.test').url(identity)
