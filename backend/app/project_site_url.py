"""Resolve one committed project's stable IP site URL without allocating ports."""
from pathlib import Path

from .project_origins import ProjectOriginError, ProjectOriginRepository
from .project_port_hosts import ProjectPortHosts


def public_project_url(database: Path, *, project_id: str, address: str,
                       first_port: int, last_port: int) -> str:
    origins = ProjectOriginRepository(database, first_port=first_port,
                                      last_port=last_port)
    pair = origins.for_project(project_id)
    if pair is None:
        raise ProjectOriginError('origin_project_unallocated')
    return ProjectPortHosts(address, origins).origin(pair.public_port) + '/'
