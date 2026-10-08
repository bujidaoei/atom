"""Bounded, cached checks of the configured authoritative snapshot store."""
from contextlib import closing
import logging
from pathlib import Path
import sqlite3
from threading import Lock
import time

from .artifacts import Artifact, ArtifactError, _describe
from .errors import AtomError


def storage_message(code: str) -> str:
    if code in ('artifact_credentials_invalid', 'artifact_signature_invalid'):
        return '文件存储认证失效，请管理员更新存储凭据后重试'
    if code == 'artifact_access_denied':
        return '文件存储权限不足，请管理员检查存储授权后重试'
    if code == 'artifact_not_found':
        return '已保存的文件版本暂不可读取，请管理员检查存储对象'
    return '文件存储暂不可用，请稍后重试或联系管理员'


class StorageUnavailable(AtomError):
    status_code = 503


class StorageReadiness:
    def __init__(self, database: Path, store, *, interval: int = 15):
        if type(interval) is not int or not 1 <= interval <= 60:
            raise ValueError('invalid_storage_probe_interval')
        self.database, self.store, self.interval = database, store, interval
        self._lock = Lock()
        self._checked = None
        self._code = 'artifact_not_initialized'

    def check(self) -> bool:
        # Never serve stale success to a caller while a probe is in flight.
        if not self._lock.acquire(timeout=9):
            return False
        try:
            if self._checked is not None and time.monotonic() - self._checked < self.interval:
                return self._code is None
            code = None
            try:
                with closing(sqlite3.connect(self.database.as_uri() + '?mode=ro',
                        uri=True, timeout=1)) as db:
                    db.execute('PRAGMA query_only=ON')
                    row = db.execute('SELECT key,revision,size FROM revision_artifacts '
                                     'ORDER BY size,key LIMIT 1').fetchone()
                if row is None:
                    raise ArtifactError('artifact_not_initialized')
                expected = Artifact(*row)
                if _describe(self.store.read(expected.key)) != expected:
                    raise ArtifactError('artifact_digest_mismatch')
            except ArtifactError as error:
                code = error.code
            except (sqlite3.Error, OSError):
                code = 'artifact_io_error'
            if code != self._code:
                logging.getLogger(__name__).warning('artifact_readiness_changed ready=%s code=%s',
                    code is None, code or 'ok',
                    extra={'storage_ready': code is None, 'storage_error_code': code})
            self._code, self._checked = code, time.monotonic()
            return code is None
        finally:
            self._lock.release()

    def require_available(self) -> None:
        if not self.check():
            raise StorageUnavailable(storage_message(self._code))
