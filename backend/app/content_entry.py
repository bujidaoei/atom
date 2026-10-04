"""Isolated content-process factory; launch with ``uvicorn --factory``."""
from dataclasses import dataclass, field
import os
from pathlib import Path

from .access_repository import AccessError
from .artifacts import ArtifactError, configured_artifact_store
from .storage_config import ObjectStorageSettings
from .content_access import ContentAccessRepository
from .content_bootstrap import ContentNavigation
from .content_hosts import ContentHostError, ContentHosts
from .content_repository import ContentRepository
from .content_service import ContentService
from .migrations import MigrationError, verify
from .project_origins import ProjectOriginError, ProjectOriginRepository
from .project_public_hosts import ProjectPublicHosts


class ContentStartupError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContentProcessConfig:
    database: Path
    artifacts: Path
    host_suffix: str
    console_origin: str
    console_base_path: str = ''
    storage: ObjectStorageSettings = field(default_factory=lambda: ObjectStorageSettings(_env_file=None), repr=False)

    def __post_init__(self):
        if (not isinstance(self.database, Path) or not self.database.is_absolute()
                or not isinstance(self.artifacts, Path) or not self.artifacts.is_absolute()):
            raise ContentStartupError('content_absolute_paths_required')
        try:
            navigation = ContentNavigation(self.console_origin, self.console_base_path)
            navigation.validate_content_hosts(ContentHosts(self.host_suffix))
        except (ValueError, ContentHostError):
            raise ContentStartupError('content_origin_configuration_invalid') from None

    @classmethod
    def from_environment(cls):
        names = ('ATOM_CONTENT_DB_PATH', 'ATOM_CONTENT_ARTIFACT_DIR',
                 'ATOM_CONTENT_HOST_SUFFIX', 'ATOM_CONTENT_CONSOLE_ORIGIN')
        try:
            database, artifacts, suffix, console = (os.environ[name] for name in names)
        except KeyError:
            raise ContentStartupError('content_configuration_missing') from None
        return cls(Path(database), Path(artifacts), suffix, console,
                   os.environ.get('ATOM_CONTENT_CONSOLE_BASE_PATH', ''))


def create_app(config: ContentProcessConfig | None = None) -> ContentService:
    """Refuse boot until the exact ledger and isolated store are usable."""
    if config is None:
        config = ContentProcessConfig.from_environment()
    if type(config) is not ContentProcessConfig:
        raise ContentStartupError('content_configuration_invalid')
    try:
        if verify(config.database) not in (13, 14, 15, 16, 17, 18, 19):
            raise ContentStartupError('content_verified_schema_required')
        store = configured_artifact_store(config.storage, config.artifacts)
        repository = ContentRepository(config.database)
        access = ContentAccessRepository(config.database)
        hosts = ContentHosts(config.host_suffix)
        navigation = ContentNavigation(config.console_origin, config.console_base_path)
        return ContentService(repository, store, hosts, access=access, navigation=navigation)
    except (MigrationError, ArtifactError, AccessError):
        raise ContentStartupError('content_startup_unavailable') from None


@dataclass(frozen=True)
class IpPublicContentConfig:
    database: Path
    artifacts: Path
    address: str
    first_port: int
    last_port: int
    storage: ObjectStorageSettings = field(default_factory=lambda: ObjectStorageSettings(_env_file=None), repr=False)

    @classmethod
    def from_environment(cls):
        names = ('ATOM_PUBLIC_DB_PATH', 'ATOM_PUBLIC_ARTIFACT_DIR',
                 'ATOM_PUBLIC_IP', 'ATOM_PUBLIC_FIRST_PORT', 'ATOM_PUBLIC_LAST_PORT')
        try:
            database, artifacts, address, first, last = (os.environ[name] for name in names)
            return cls(Path(database), Path(artifacts), address, int(first), int(last))
        except (KeyError, ValueError):
            raise ContentStartupError('public_configuration_missing') from None


def create_ip_public_app(config: IpPublicContentConfig | None = None) -> ContentService:
    """Serve only live public snapshots from immutable per-project IP ports."""
    if config is None:
        config = IpPublicContentConfig.from_environment()
    if (type(config) is not IpPublicContentConfig
            or not isinstance(config.database, Path) or not isinstance(config.artifacts, Path)
            or not config.database.is_absolute() or not config.artifacts.is_absolute()):
        raise ContentStartupError('public_configuration_invalid')
    try:
        origins = ProjectOriginRepository(config.database, first_port=config.first_port,
                                          last_port=config.last_port)
        store = configured_artifact_store(config.storage, config.artifacts)
        repository = ContentRepository(config.database)
        hosts = ProjectPublicHosts(config.address, origins, repository)
        return ContentService(repository, store, hosts)
    except (MigrationError, ArtifactError, AccessError, ProjectOriginError,
            ContentHostError, ValueError, OSError):
        raise ContentStartupError('public_startup_unavailable') from None
