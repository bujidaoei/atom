"""Static content profile namespace policy; never silently drops project files."""
from .snapshots import VerifiedSnapshot

CONTROL_NAMESPACE = '_atom'

# Local submit events are part of the static application contract. Native
# transport remains forbidden by form-action even when sandbox permits events.
# All delivered and verified artifacts use this policy; preview may override
# only frame-ancestors to permit its configured console embedding.
GENERATED_CONTENT_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'none'; worker-src 'none'; object-src 'none'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; "
    "sandbox allow-scripts allow-same-origin allow-forms"
)

GENERATED_CONTENT_HEADERS = {
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'Content-Security-Policy': GENERATED_CONTENT_CSP,
}


class ContentPolicyError(ValueError):
    pass


def is_control_path(path: str) -> bool:
    return path.lstrip('/').split('/',1)[0].casefold() == CONTROL_NAMESPACE


def validate_content_manifest(manifest: VerifiedSnapshot) -> None:
    if any(entry.path.split('/',1)[0].casefold()==CONTROL_NAMESPACE for entry in manifest.files):
        raise ContentPolicyError('reserved_content_path')
