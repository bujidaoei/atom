"""Deterministic Caddy configuration from committed IP-origin reservations."""
from dataclasses import dataclass
from ipaddress import ip_address
import re
from urllib.parse import urlsplit

from .project_origins import OriginRoute, ProjectOriginRepository


class IngressError(ValueError):
    pass


_UPSTREAM = re.compile(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*'
                       r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?:'
                       r'(?:[1-9][0-9]{0,4})\Z')
_DIRECTORY = re.compile(r'https://[A-Za-z0-9./:_-]+\Z')
_MARKER = '# atom-project-origins: generated from schema17\n'


@dataclass(frozen=True)
class IpIngressConfig:
    address: str
    preview_upstream: str
    public_upstream: str
    acme_directory: str

    def __post_init__(self):
        if not isinstance(self.address, str):
            raise IngressError('invalid_ingress_address')
        try:
            parsed = ip_address(self.address.strip('[]'))
        except ValueError:
            raise IngressError('invalid_ingress_address') from None
        canonical = f'[{parsed.compressed}]' if parsed.version == 6 else parsed.compressed
        if canonical != self.address:
            raise IngressError('invalid_ingress_address')
        for upstream in (self.preview_upstream, self.public_upstream):
            if not isinstance(upstream, str) or _UPSTREAM.fullmatch(upstream) is None:
                raise IngressError('invalid_ingress_upstream')
            if not 1 <= int(upstream.rsplit(':', 1)[1]) <= 65535:
                raise IngressError('invalid_ingress_upstream')
        directory = self.acme_directory
        if not isinstance(directory, str) or _DIRECTORY.fullmatch(directory) is None:
            raise IngressError('invalid_acme_directory')
        try:
            parsed_url = urlsplit(directory)
            valid = (parsed_url.scheme == 'https' and bool(parsed_url.hostname)
                     and parsed_url.port is None and parsed_url.username is None
                     and parsed_url.password is None and bool(parsed_url.path))
        except ValueError:
            valid = False
        if not valid:
            raise IngressError('invalid_acme_directory')


def render_ip_caddyfile(base: str, repository: ProjectOriginRepository,
                        config: IpIngressConfig) -> str:
    """Render exact listeners; this function never reloads or mutates Caddy."""
    if not isinstance(repository, ProjectOriginRepository):
        raise IngressError('invalid_ingress_configuration')
    return render_ip_routes(base, repository.active_routes(), config)


def render_ip_routes(base: str, routes: tuple[OriginRoute, ...],
                     config: IpIngressConfig) -> str:
    if (not isinstance(base, str) or not base.strip() or '\0' in base
            or _MARKER.strip() in base):
        raise IngressError('invalid_base_caddyfile')
    if not isinstance(routes, tuple) or not isinstance(config, IpIngressConfig):
        raise IngressError('invalid_ingress_configuration')
    blocks = []
    seen = set()
    for route in routes:
        if (not isinstance(route, OriginRoute) or route.purpose not in ('preview', 'public')
                or type(route.port) is not int or not 1024 <= route.port <= 65535
                or route.port in seen):
            raise IngressError('invalid_origin_route')
        seen.add(route.port)
        authority = f'{config.address}:{route.port}'
        if authority in base:
            raise IngressError('ingress_port_already_configured')
        upstream = config.preview_upstream if route.purpose == 'preview' else config.public_upstream
        blocks.append(f'''https://{authority} {{
  tls {{
    issuer acme {{
      dir {config.acme_directory}
      profile shortlived
      disable_tlsalpn_challenge
    }}
  }}
  reverse_proxy {upstream}
}}
''')
    return base.rstrip() + '\n\n' + _MARKER + '\n'.join(blocks)
