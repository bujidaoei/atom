"""Canonical Host parsing for immutable project roles on one IP address."""
from dataclasses import dataclass
from ipaddress import ip_address

from .content_hosts import ContentHostError
from .project_origins import OriginRoute, ProjectOriginRepository


@dataclass(frozen=True)
class ProjectPortHosts:
    address: str
    origins: ProjectOriginRepository

    def __post_init__(self):
        if not isinstance(self.address, str) or not isinstance(self.origins, ProjectOriginRepository):
            raise ContentHostError('invalid_project_address')
        try:
            parsed = ip_address(self.address.strip('[]'))
        except ValueError:
            raise ContentHostError('invalid_project_address') from None
        canonical = f'[{parsed.compressed}]' if parsed.version == 6 else parsed.compressed
        if self.address != canonical:
            raise ContentHostError('invalid_project_address')

    def route(self, headers: list[tuple[bytes, bytes]], *, purpose: str) -> OriginRoute:
        if purpose not in ('preview', 'public'):
            raise ContentHostError('invalid_content_host')
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
        if route is None or route.purpose != purpose:
            raise ContentHostError('invalid_content_host')
        return route

    def origin(self, port: int) -> str:
        if type(port) is not int or not self.origins.first_port <= port <= self.origins.last_port:
            raise ContentHostError('invalid_content_host')
        return f'https://{self.address}:{port}'
