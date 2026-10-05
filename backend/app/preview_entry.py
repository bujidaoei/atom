"""Isolated owner-preview process factory; launch with ``uvicorn --factory``."""
from dataclasses import dataclass, field
import os
from pathlib import Path

from .artifacts import ArtifactError, configured_artifact_store
from .content_hosts import ContentHostError
from .preview_access import PreviewAccessError, PreviewAccessRepository
from .preview_service import PreviewService
from .project_origins import ProjectOriginError, ProjectOriginRepository
from .project_port_hosts import ProjectPortHosts
from .storage_config import ObjectStorageSettings


class PreviewStartupError(RuntimeError):
    pass


@dataclass(frozen=True)
class IpPreviewConfig:
    database: Path
    artifacts: Path
    address: str
    first_port: int
    last_port: int
    storage: ObjectStorageSettings = field(default_factory=lambda: ObjectStorageSettings(_env_file=None),
                                           repr=False)

    @classmethod
    def from_environment(cls):
        names = ('ATOM_PREVIEW_DB_PATH', 'ATOM_PREVIEW_ARTIFACT_DIR',
                 'ATOM_PREVIEW_IP', 'ATOM_PREVIEW_FIRST_PORT', 'ATOM_PREVIEW_LAST_PORT')
        try:
            database, artifacts, address, first, last = (os.environ[name] for name in names)
            return cls(Path(database), Path(artifacts), address, int(first), int(last))
        except (KeyError, ValueError):
            raise PreviewStartupError('preview_configuration_missing') from None


def create_ip_preview_app(config: IpPreviewConfig | None = None) -> PreviewService:
    if config is None:
        config = IpPreviewConfig.from_environment()
    if (type(config) is not IpPreviewConfig or not isinstance(config.database, Path)
            or not isinstance(config.artifacts, Path) or not config.database.is_absolute()
            or not config.artifacts.is_absolute()):
        raise PreviewStartupError('preview_configuration_invalid')
    try:
        origins = ProjectOriginRepository(config.database, first_port=config.first_port,
                                          last_port=config.last_port)
        access = PreviewAccessRepository(config.database)
        hosts = ProjectPortHosts(config.address, origins)
        store = configured_artifact_store(config.storage, config.artifacts)
        return PreviewService(access, store, hosts)
    except (PreviewAccessError, ProjectOriginError, ContentHostError, ArtifactError,
            ValueError, OSError):
        raise PreviewStartupError('preview_startup_unavailable') from None
