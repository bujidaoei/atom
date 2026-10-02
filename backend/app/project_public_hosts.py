"""Exact Host-to-project routing for public pages on an IP-only installation."""
from dataclasses import dataclass
from ipaddress import ip_address

from .content_hosts import ContentHostError
from .content_repository import ContentRepository
from .project_origins import ProjectOriginRepository


@dataclass(frozen=True)
class ProjectPublicHosts:
    address: str
    origins: ProjectOriginRepository
    content: ContentRepository

    def __post_init__(self):
        if not isinstance(self.address, str):
            raise ContentHostError('invalid_public_address')
        try:
            parsed = ip_address(self.address.strip('[]'))
        except ValueError:
            raise ContentHostError('invalid_public_address') from None
        canonical = f'[{parsed.compressed}]' if parsed.version == 6 else parsed.compressed
        if self.address != canonical or self.origins.path.resolve() != self.content.path.resolve():
            raise ContentHostError('invalid_public_address')

    def route(self, headers: list[tuple[bytes, bytes]]) -> str:
        values = [value for key, value in headers if key.lower() == b'host']
        if len(values) != 1 or not isinstance(values[0], bytes) or len(values[0]) > 64:
            raise ContentHostError('invalid_content_host')
        try:
            authority = values[0].decode('ascii')
        except UnicodeError:
            raise ContentHostError('invalid_content_host') from None
        prefix = self.address + ':'
        if not authority.startswith(prefix):
            raise ContentHostError('invalid_content_host')
        port_text = authority[len(prefix):]
        if not port_text.isascii() or not port_text.isdecimal() or port_text.startswith('0'):
            raise ContentHostError('invalid_content_host')
        port = int(port_text)
        if not self.origins.first_port <= port <= self.origins.last_port:
            raise ContentHostError('invalid_content_host')
        route = self.origins.route(port)
        if route is None or route.purpose != 'public':
            raise ContentHostError('invalid_content_host')
        return self.content.public_project_binding(project_id=route.project_id).id
