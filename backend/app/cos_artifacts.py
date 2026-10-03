"""Private, content-addressed COS snapshots with bounded SDK process lifetime."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from threading import BoundedSemaphore

from .artifacts import ArtifactError, _describe
from .snapshots import MAX_ARCHIVE_BYTES

_OPERATIONS = BoundedSemaphore(1)
_ERRORS = {'artifact_not_found', 'artifact_io_error', 'artifact_digest_mismatch',
           'invalid_artifact', 'artifact_transport_timeout'}


class CosArtifactStore:
    @property
    def local_root(self) -> None:
        return None

    def __init__(self, settings, *, operation_seconds=45):
        if (settings.storage_backend != 'cos' or type(operation_seconds) not in (int, float)
                or not 1 <= operation_seconds <= 60):
            raise ArtifactError('invalid_artifact_configuration')
        self._configuration = {
            'region': settings.storage_s3_region, 'endpoint': settings.storage_s3_endpoint,
            'bucket': settings.storage_s3_bucket, 'prefix': settings.storage_s3_prefix,
            'access_key': settings.storage_s3_access_key.get_secret_value(),
            'secret_key': settings.storage_s3_secret_key.get_secret_value(),
        }
        self._seconds = operation_seconds

    def _invoke(self, operation, key, payload=b''):
        if type(key) is not str or re.fullmatch(r'[0-9a-f]{64}', key) is None:
            raise ArtifactError('invalid_artifact_key')
        if not _OPERATIONS.acquire(timeout=3):
            raise ArtifactError('artifact_store_busy')
        try:
            control = json.dumps(self._configuration | {'operation': operation, 'key': key},
                                 separators=(',', ':')).encode() + b'\n'
            root = Path(__file__).resolve().parents[1]
            environment = {key: value for key, value in os.environ.items()
                           if key.upper() in ('SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'LANG')}
            environment['PYTHONPATH'] = str(root)
            result = subprocess.run([sys.executable, '-m', 'app.cos_artifact_worker'],
                input=control + payload, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=self._seconds, cwd=root, env=environment,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if result.returncode or not result.stdout.startswith(b'OK\n'):
                code = result.stdout.removeprefix(b'ERROR\n').decode('ascii', errors='replace')
                raise ArtifactError(code if code in _ERRORS else 'artifact_io_error')
            recovered = result.stdout[3:]
            if len(recovered) > MAX_ARCHIVE_BYTES or _describe(recovered).key != key:
                raise ArtifactError('artifact_digest_mismatch')
            return recovered
        except subprocess.TimeoutExpired:
            # subprocess.run kills and reaps this owned worker before raising.
            raise ArtifactError('artifact_transport_timeout') from None
        except OSError:
            raise ArtifactError('artifact_io_error') from None
        finally:
            _OPERATIONS.release()

    def read(self, key: str) -> bytes:
        return self._invoke('read', key)

    def put(self, payload: bytes):
        artifact = _describe(payload)
        if self._invoke('put', artifact.key, payload) != payload:
            raise ArtifactError('artifact_digest_mismatch')
        return artifact
