"""Exact Host-to-project routing for public pages on an IP-only installation."""
from dataclasses import dataclass
from .content_hosts import ContentHostError
from .content_repository import ContentRepository
from .project_origins import ProjectOriginRepository
from .project_port_hosts import ProjectPortHosts


@dataclass(frozen=True)
class ProjectPublicHosts:
    address: str
    origins: ProjectOriginRepository
    content: ContentRepository

    def __post_init__(self):
        try:
            ProjectPortHosts(self.address, self.origins)
        except ContentHostError:
            raise ContentHostError('invalid_public_address') from None
        if self.origins.path.resolve() != self.content.path.resolve():
            raise ContentHostError('invalid_public_address')

    def route(self, headers: list[tuple[bytes, bytes]]) -> str:
        route = ProjectPortHosts(self.address, self.origins).route(headers, purpose='public')
        return self.content.public_project_binding(project_id=route.project_id).id
