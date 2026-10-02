"""Deterministic Caddy configuration from committed IP-origin reservations."""
from dataclasses import dataclass
from ipaddress import ip_address
import json
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener
from urllib.parse import urlsplit

from .project_origins import OriginRoute, ProjectOriginRepository


class IngressError(ValueError):
    pass


_UPSTREAM = re.compile(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*'
                       r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?:'
                       r'(?:[1-9][0-9]{0,4})\Z')
_DIRECTORY = re.compile(r'https://[A-Za-z0-9./:_-]+\Z')
_MARKER = '# atom-project-origins: generated from schema17\n'
HEALTH_PATH = '/_atom/health'


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        return None


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


def probe_ip_routes(routes: tuple[OriginRoute, ...], address: str, *,
                    tls_context: ssl.SSLContext | None = None,
                    timeout_seconds: float = 5) -> None:
    """Verify each TLS listener answers for its exact committed role/project.

    No ambient proxy, cookie or insecure TLS fallback is permitted. This checks
    the listener from the caller's network location; deployment also needs an
    independent external reachability check before enabling publication.
    """
    if (not isinstance(routes, tuple) or not isinstance(address, str)
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < timeout_seconds <= 15):
        raise IngressError('invalid_ingress_probe')
    try:
        parsed = ip_address(address.strip('[]'))
        canonical = f'[{parsed.compressed}]' if parsed.version == 6 else parsed.compressed
        if canonical != address:
            raise ValueError
    except ValueError:
        raise IngressError('invalid_ingress_probe') from None
    opener = build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(
        context=tls_context or ssl.create_default_context()))
    for route in routes:
        if (not isinstance(route, OriginRoute) or route.purpose not in ('preview', 'public')
                or type(route.port) is not int or not 1024 <= route.port <= 65535):
            raise IngressError('invalid_origin_route')
        url = f'https://{address}:{route.port}{HEALTH_PATH}'
        try:
            with opener.open(Request(url, headers={'Accept':'application/json'}),
                             timeout=timeout_seconds) as response:
                if (response.status != 200 or
                        response.headers.get_content_type() != 'application/json'
                        or response.headers.get('Cache-Control') != 'no-store'
                        or response.headers.get_all('Set-Cookie')):
                    raise IngressError('ingress_probe_mismatch')
                raw = response.read(513)
            if len(raw) > 512:
                raise IngressError('ingress_probe_mismatch')
            body = json.loads(raw)
            if (type(body) is not dict or body != {'purpose':route.purpose,
                                                   'projectId':route.project_id}):
                raise IngressError('ingress_probe_mismatch')
        except IngressError:
            raise
        except (HTTPError, URLError, TimeoutError, ssl.SSLError, OSError,
                UnicodeError, ValueError):
            raise IngressError('ingress_probe_unavailable') from None
