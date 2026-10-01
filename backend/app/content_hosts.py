"""Strict content-host syntax. DNS/site ownership is a deployment concern."""
from dataclasses import dataclass
import re


class ContentHostError(ValueError):
    pass


@dataclass(frozen=True)
class ContentHosts:
    suffix: str

    def __post_init__(self):
        # Require configured ASCII DNS labels; never repair URLs, IDNs or dots.
        value = self.suffix
        if (not isinstance(value,str) or not 3 <= len(value) <= 218 or value != value.lower()
            or len(value.split('.')) < 2 or any(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label) is None
                                              for label in value.split('.'))
            or re.fullmatch(r'[a-z][a-z0-9-]*',value.split('.')[-1]) is None):
            raise ContentHostError('invalid_content_suffix')

    def hostname(self, binding_id: str) -> str:
        if not isinstance(binding_id,str) or re.fullmatch(r'[0-9a-f]{32}',binding_id) is None:
            raise ContentHostError('invalid_content_binding')
        return f'r-{binding_id}.{self.suffix}'

    def url(self, binding_id: str) -> str:
        return 'https://' + self.hostname(binding_id) + '/'

    def sharing_url(self, slug: str) -> str:
        if (not isinstance(slug,str) or len(slug)>63
                or re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',slug) is None):
            raise ContentHostError('invalid_content_slug')
        return f'https://share.{self.suffix}/s/{slug}'

    def binding(self, headers: list[tuple[bytes, bytes]]) -> str:
        binding = self.route(headers)
        if binding is None:
            raise ContentHostError('invalid_content_host')
        return binding

    def route(self, headers: list[tuple[bytes, bytes]]) -> str | None:
        """Return a pinned binding, or None for the dedicated sharing host.

        Use exactly one actual Host header, never forwarded host metadata.
        An ingress must preserve the validated authority in Host. This parser
        does not assert TLS, DNS ownership, registrable-site isolation or auth.
        """
        values = [value for key,value in headers if key.lower() == b'host']
        if len(values) != 1:
            raise ContentHostError('invalid_content_host')
        raw = values[0]
        if not isinstance(raw,bytes) or len(raw)>257:
            raise ContentHostError('invalid_content_host')
        try:
            host = raw.decode('ascii').lower()
        except UnicodeError:
            raise ContentHostError('invalid_content_host') from None
        if host.endswith(':443'):
            host = host[:-4]
        if host == 'share.' + self.suffix:
            return None
        match = re.fullmatch(r'r-([0-9a-f]{32})\.' + re.escape(self.suffix),host)
        if match is None:
            raise ContentHostError('invalid_content_host')
        return match.group(1)
