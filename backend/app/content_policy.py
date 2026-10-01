"""Static content profile namespace policy; never silently drops project files."""
from .snapshots import VerifiedSnapshot

CONTROL_NAMESPACE = '_atom'


class ContentPolicyError(ValueError):
    pass


def is_control_path(path: str) -> bool:
    return path.lstrip('/').split('/',1)[0].casefold() == CONTROL_NAMESPACE


def validate_content_manifest(manifest: VerifiedSnapshot) -> None:
    if any(entry.path.split('/',1)[0].casefold()==CONTROL_NAMESPACE for entry in manifest.files):
        raise ContentPolicyError('reserved_content_path')
