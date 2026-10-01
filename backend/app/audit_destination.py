"""Operator-approved audit endpoint and TLS connection pinned to public addresses."""
import asyncio
from dataclasses import dataclass, field
import hashlib
import ipaddress
import json
import re
import socket
import ssl


class AuditDestinationError(RuntimeError):
    pass


def _public_address(value):
    try:
        if not isinstance(value, str) or '%' in value:
            raise ValueError
        address = ipaddress.ip_address(value)
        if (str(address) != value or not address.is_global or address.is_multicast or
                address.is_reserved or address.is_loopback or address.is_link_local or
                address.is_unspecified):
            raise ValueError
        if address.version == 6 and (address.ipv4_mapped is not None or
                address.sixtofour is not None or address.teredo is not None or
                address not in ipaddress.ip_network('2000::/3')):
            raise ValueError
        return address
    except ValueError:
        raise AuditDestinationError('invalid_audit_address') from None


@dataclass(frozen=True)
class AuditDestination:
    host: str
    path: str
    addresses: tuple[str, ...]
    scope_kind: str
    scope_id: str
    token: str = field(repr=False)

    def __post_init__(self):
        if (not isinstance(self.host, str) or not 1 <= len(self.host) <= 253 or
                self.host != self.host.lower() or '.' not in self.host or
                re.fullmatch(r'[a-z0-9.-]+', self.host) is None or
                any(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part) is None
                    for part in self.host.split('.')) or self.host.split('.')[-1].isdigit()):
            raise AuditDestinationError('invalid_audit_host')
        if (not isinstance(self.path, str) or not 1 <= len(self.path) <= 256 or
                re.fullmatch(r'/[A-Za-z0-9_./~-]*', self.path) is None or
                '//' in self.path or any(part in ('.', '..') for part in self.path.split('/'))):
            raise AuditDestinationError('invalid_audit_path')
        if (type(self.addresses) is not tuple or not 1 <= len(self.addresses) <= 8 or
                any(not isinstance(address, str) for address in self.addresses) or
                len(set(self.addresses)) != len(self.addresses)):
            raise AuditDestinationError('invalid_audit_addresses')
        for address in self.addresses:
            _public_address(address)
        if (self.scope_kind not in ('account', 'project') or not isinstance(self.scope_id, str) or
                re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', self.scope_id) is None):
            raise AuditDestinationError('invalid_audit_scope')
        if not isinstance(self.token, str) or re.fullmatch(r'[A-Za-z0-9._~+/-]{32,512}=*', self.token) is None or len(self.token)>512:
            raise AuditDestinationError('invalid_audit_token')

    @property
    def destination_id(self):
        # Credential/IP rotation retains delivery identity; logical receiver/scope changes do not.
        identity = [1, 'https', self.host, 443, self.path, self.scope_kind, self.scope_id]
        return hashlib.sha256(json.dumps(identity, separators=(',', ':')).encode('ascii')).hexdigest()


async def connect_audit_tls(destination: AuditDestination, *, ca_file=None):
    """Connect only to an approved numeric IP, preserving hostname TLS verification.

    Caller owns the returned stream and must close it. No DNS, proxy, redirects,
    application bytes or credential transmission occurs in this function.
    """
    if type(destination) is not AuditDestination:
        raise AuditDestinationError('invalid_audit_destination')
    try:
        context = ssl.create_default_context(cafile=ca_file)
    except (OSError, ssl.SSLError):
        raise AuditDestinationError('invalid_audit_trust_store') from None
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.set_alpn_protocols(['http/1.1'])
    try:
        async with asyncio.timeout(10):
            for value in destination.addresses:
                address = _public_address(value)
                raw = socket.socket(socket.AF_INET if address.version == 4 else socket.AF_INET6, socket.SOCK_STREAM)
                raw.setblocking(False)
                writer = None
                transferred = False
                try:
                    async with asyncio.timeout(3):
                        await asyncio.get_running_loop().sock_connect(raw, (value, 443))
                        reader, writer = await asyncio.open_connection(sock=raw, ssl=context,
                            server_hostname=destination.host, ssl_handshake_timeout=2,
                            ssl_shutdown_timeout=1, limit=16384)
                    transferred = True
                    return reader, writer
                except (OSError, TimeoutError):
                    pass
                finally:
                    if not transferred:
                        if writer is not None:
                            writer.close()
                        else:
                            raw.close()
    except (OSError, TimeoutError):
        pass
    raise AuditDestinationError('audit_destination_unavailable') from None
