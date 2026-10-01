import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import pytest

from app.audit_destination import AuditDestination, AuditDestinationError, connect_audit_tls


def destination(**changes):
    values = dict(host='audit.example.org', path='/events', addresses=('8.8.8.8',),
                  scope_kind='account', scope_id='user', token='synthetic-audit-token-with-32-characters')
    return AuditDestination(**(values|changes))


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.1', '169.254.169.254', '172.16.0.1',
    '192.168.1.1', '100.64.0.1', '0.0.0.0', '224.0.0.1', '255.255.255.255', '192.0.2.1',
    '::1', '::', 'fc00::1', 'fe80::1', 'fe80::1%eth0', 'ff02::1', '::ffff:8.8.8.8',
    '2002:808:808::1', '2001::1', '64:ff9b::808:808', '2001:db8::1', '008.008.008.008',
    '0x08080808', '134744072', 'dns.example.org'])
def test_nonpublic_or_ambiguous_addresses_denied(address):
    with pytest.raises(AuditDestinationError):
        destination(addresses=(address,))


@pytest.mark.parametrize('changes', [
    {'host': 'https://audit.example.org'}, {'host': 'user:pass@audit.example.org'},
    {'host': 'audit.example.org:443'}, {'host': 'audit.example.org.'}, {'host': 'Audit.example.org'},
    {'host': '8.8.8.8'}, {'host': 'audit..example.org'}, {'host': 'audit.example.org\r\nx: y'},
    {'path': '//example.org'}, {'path': '/a/../events'}, {'path': '/events?key=secret'},
    {'path': '/%2e%2e/x'}, {'path': '/events#key'}, {'path': '/x\r\ny'},
    {'addresses': ()}, {'addresses': ['8.8.8.8']}, {'addresses': ('8.8.8.8', '8.8.8.8')},
    {'scope_kind': 'tenant'}, {'scope_id': '../user'}, {'token': 'short'},
    {'token': 'a'*32+'\r\nx: y'}, {'token': 'a'*513},
])
def test_invalid_configuration_redacted(changes):
    with pytest.raises(AuditDestinationError) as caught:
        destination(**changes)
    assert 'synthetic' not in str(caught.value) and 'secret' not in str(caught.value)


def test_immutable_identity_preserves_token_ip_rotation_and_binds_receiver_scope():
    target = destination(addresses=('8.8.8.8', '2606:4700:4700::1111'))
    assert target.token not in repr(target)
    assert len(target.destination_id) == 64
    assert replace(target, token='replacement-token-with-32-characters').destination_id == target.destination_id
    assert replace(target, addresses=('1.1.1.1',)).destination_id == target.destination_id
    for changes in ({'host': 'other.example.org'}, {'path': '/other'}, {'scope_id': 'other'}, {'scope_kind': 'project'}):
        assert replace(target, **changes).destination_id != target.destination_id


@pytest.fixture
def certificate(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'audit.example.org')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(True, False, True, False, False, True, True, False, False), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('audit.example.org')]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256()))
    key_path, cert_path = tmp_path/'key.pem', tmp_path/'cert.pem'
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


@pytest.mark.parametrize('case', ['valid', 'wrong-host', 'untrusted', 'failover', 'cancel', 'stall'])
def test_real_tls_with_pinned_socket_and_no_dns(certificate, monkeypatch, case):
    cert, key = certificate
    async def scenario():
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        names, seen, connected = [], [], asyncio.Event()
        context.set_servername_callback(lambda _socket, name, _context: names.append(name))
        held = []
        stalled_readers = []
        async def receiver(reader, writer):
            held.append(writer)
            connected.set()
            if case in ('cancel', 'stall'):
                stalled_readers.append(reader)
            else:
                seen.append(await reader.read(1))
                writer.close()
        server = await asyncio.start_server(receiver, '127.0.0.1', 0,
                                           ssl=None if case in ('cancel', 'stall') else context)
        port = server.sockets[0].getsockname()[1]
        loop = asyncio.get_running_loop()
        original = loop.sock_connect
        attempts = []
        async def routed(sock, address):
            # Only the OS socket route is redirected to this disposable TLS server.
            # Production policy, TLS verification, SNI and timeouts are unchanged.
            attempts.append(address)
            assert address in [('8.8.8.8', 443), ('1.1.1.1', 443)]
            if case == 'failover' and address[0] == '8.8.8.8':
                raise OSError('fixture_refusal')
            await original(sock, ('127.0.0.1', port))
        async def no_dns(*args, **kwargs):
            raise AssertionError('DNS must not be used')
        monkeypatch.setattr(loop, 'sock_connect', routed)
        monkeypatch.setattr(loop, 'getaddrinfo', no_dns)
        monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:1')
        target = destination(host='wrong.example.org' if case == 'wrong-host' else 'audit.example.org',
                             addresses=('8.8.8.8', '1.1.1.1') if case == 'failover' else ('8.8.8.8',))
        try:
            task = asyncio.create_task(connect_audit_tls(target, ca_file=None if case == 'untrusted' else cert))
            if case == 'cancel':
                await asyncio.wait_for(connected.wait(), 2)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            elif case in ('wrong-host', 'untrusted', 'stall'):
                with pytest.raises(AuditDestinationError, match='unavailable'):
                    await asyncio.wait_for(task, 4)
            else:
                reader, writer = await asyncio.wait_for(task, 4)
                assert writer.get_extra_info('ssl_object').version() in ('TLSv1.2', 'TLSv1.3')
                writer.write(b'x')
                await writer.drain()
                assert await reader.read() == b''
                writer.close()
                await writer.wait_closed()
                assert names == ['audit.example.org'] and seen == [b'x']
            assert len(attempts) == (2 if case == 'failover' else 1)
            for reader in stalled_readers:
                # EOF proves the cancelled/expired handshake closed its underlying socket.
                data = await asyncio.wait_for(reader.read(), 2)
                assert target.token.encode() not in data
        finally:
            for writer in held:
                writer.close()
            server.close()
            await server.wait_closed()
    asyncio.run(scenario())
