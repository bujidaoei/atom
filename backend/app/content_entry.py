"""Isolated content-process factory; launch with ``uvicorn --factory``."""
from dataclasses import dataclass
import os
from pathlib import Path

from .access_repository import AccessError
from .artifacts import ArtifactError, ArtifactStore
from .content_access import ContentAccessRepository
from .content_bootstrap import ContentNavigation
from .content_hosts import ContentHostError, ContentHosts
from .content_repository import ContentRepository
from .content_service import ContentService
from .migrations import MigrationError, verify


class ContentStartupError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContentProcessConfig:
    database: Path
    artifacts: Path
    host_suffix: str
    console_origin: str

    def __post_init__(self):
        if (not isinstance(self.database, Path) or not self.database.is_absolute()
                or not isinstance(self.artifacts, Path) or not self.artifacts.is_absolute()):
            raise ContentStartupError('content_absolute_paths_required')
        try:
            navigation = ContentNavigation(self.console_origin)
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
        return cls(Path(database), Path(artifacts), suffix, console)


def create_app(config: ContentProcessConfig | None = None) -> ContentService:
    """Refuse boot until the exact ledger and isolated store are usable."""
    if config is None:
        config = ContentProcessConfig.from_environment()
    if type(config) is not ContentProcessConfig:
        raise ContentStartupError('content_configuration_invalid')
    try:
        if verify(config.database) not in (13, 14):
            raise ContentStartupError('content_verified_schema_required')
        store = ArtifactStore(config.artifacts)
        repository = ContentRepository(config.database)
        access = ContentAccessRepository(config.database)
        hosts = ContentHosts(config.host_suffix)
        navigation = ContentNavigation(config.console_origin)
        return ContentService(repository, store, hosts, access=access, navigation=navigation)
    except (MigrationError, ArtifactError, AccessError):
        raise ContentStartupError('content_startup_unavailable') from None
