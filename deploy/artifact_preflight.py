"""Enforce real COS write/readback before any forward maintenance mutation."""
from pathlib import Path
import re
import sqlite3

import forward_schema
import ip_cutover_apply
import ip_forward_capture
import protected_cutover


class ArtifactPreflightError(RuntimeError):
    """Credential-free failure; the standalone storage CLI gives fixed details."""


def verify(*, config, source: Path, image: str, storage_env: Path):
    if (not source.is_absolute() or not storage_env.is_absolute()
            or protected_cutover.IMAGE.fullmatch(image) is None):
        raise ArtifactPreflightError('invalid_storage_preflight_source')
    try:
        ip_forward_capture._private_path(source, directory=True)
        ip_forward_capture._private_path(storage_env, directory=False)
        result = ip_cutover_apply._json_command([
            str(config.docker), 'run', '--rm', '--network', 'bridge', '--read-only',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--tmpfs', '/tmp:size=64m', '--volume', f'{source / "data"}:/data:ro',
            '--env-file', str(storage_env), '--workdir', '/app/backend',
            '--entrypoint', '/app/backend/.venv/bin/python', image,
            '-m', 'app.storage_preflight', '--database', '/data/atom.db'], timeout=600)
        valid = (result.get('ok') is True and result.get('write_readback') is True
            and result.get('schema_version') == forward_schema.version(source / 'data' / 'atom.db')
            and type(result.get('artifact_count')) is int and 0 <= result['artifact_count'] <= 10000
            and type(result.get('artifact_bytes')) is int and result['artifact_bytes'] >= 0
            and all(type(result.get(key)) is str and re.fullmatch(r'[0-9a-f]{64}', result[key])
                    for key in ('probe_key', 'inventory_sha256')))
        if not valid:
            raise ArtifactPreflightError('storage_preflight_receipt_mismatch')
        return result
    except (ip_forward_capture.CaptureError, ip_cutover_apply.ApplyError,
            protected_cutover.CutoverError, sqlite3.Error, OSError) as error:
        raise ArtifactPreflightError('storage_preflight_failed') from error
