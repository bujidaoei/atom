"""Offline, idempotent transfer of registered local snapshots to private COS.

Run before switching authoritative reads. A successful transfer receipt covers
one stable ledger inventory; the operator repeats it after quiescing writers.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .artifacts import Artifact, ArtifactError, ArtifactStore, SnapshotStore, _describe
from .migrations import MigrationError, verify
from .storage_config import ObjectStorageSettings
from .snapshots import MAX_ARCHIVE_BYTES


_DIGEST = re.compile(r'[0-9a-f]{64}\Z')


class TransferError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class TransferReceipt:
    schema_version: int
    artifact_count: int
    artifact_bytes: int
    inventory_sha256: str


def _inventory(database: Path, *, maximum: int) -> tuple[tuple[Artifact, ...], int, str]:
    try:
        version = verify(database)
        if version not in (10, 11, 12, 13, 14, 15, 16, 17, 18):
            raise TransferError('unsupported_transfer_schema')
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True,
                                     timeout=3, isolation_level=None)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            if db.execute('PRAGMA user_version').fetchone()[0] != version:
                raise TransferError('transfer_inventory_changed')
            rows = db.execute('SELECT key,revision,size FROM revision_artifacts ORDER BY key,revision LIMIT ?',
                              (maximum + 1,)).fetchall()
            if len(rows) > maximum:
                raise TransferError('transfer_capacity')
            entries = tuple(Artifact(*row) for row in rows)
            for entry in entries:
                if (type(entry.key) is not str or _DIGEST.fullmatch(entry.key) is None or
                        type(entry.revision) is not str or _DIGEST.fullmatch(entry.revision) is None or
                        type(entry.size) is not int or not 14 <= entry.size <= MAX_ARCHIVE_BYTES):
                    raise TransferError('invalid_transfer_inventory')
            canonical = json.dumps([entry.__dict__ for entry in entries],
                                   sort_keys=True, separators=(',', ':')).encode()
            return entries, version, hashlib.sha256(canonical).hexdigest()
    except (MigrationError, sqlite3.Error, OSError):
        raise TransferError('transfer_inventory_unavailable') from None


def transfer_registered(database: Path, local: SnapshotStore, remote: SnapshotStore,
                        *, maximum: int = 10000) -> TransferReceipt:
    if (type(maximum) is not int or not 1 <= maximum <= 10000
            or not isinstance(database, Path) or not database.is_absolute()
            or not callable(getattr(local, 'read', None))
            or not callable(getattr(remote, 'put', None))
            or not callable(getattr(remote, 'read', None))):
        raise TransferError('invalid_transfer_configuration')
    entries, version, digest = _inventory(database, maximum=maximum)
    total = 0
    for expected in entries:
        try:
            payload = local.read(expected.key)
            if _describe(payload) != expected:
                raise TransferError('transfer_source_mismatch')
            if remote.put(payload) != expected or remote.read(expected.key) != payload:
                raise TransferError('transfer_destination_mismatch')
        except ArtifactError:
            raise TransferError('transfer_artifact_unavailable') from None
        total += expected.size
    _, final_version, final_digest = _inventory(database, maximum=maximum)
    if final_version != version or final_digest != digest:
        raise TransferError('transfer_inventory_changed')
    return TransferReceipt(version, len(entries), total, digest)


def main() -> None:
    parser = argparse.ArgumentParser(description='Verify registered local snapshots in private COS')
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--local-artifacts', type=Path, required=True)
    args = parser.parse_args()
    try:
        if not args.database.is_absolute() or not args.local_artifacts.is_absolute():
            raise TransferError('invalid_transfer_configuration')
        settings = ObjectStorageSettings(_env_file=None)
        if settings.storage_backend != 'cos':
            raise TransferError('cos_transfer_configuration_required')
        from .cos_artifacts import CosArtifactStore
        receipt = transfer_registered(args.database, ArtifactStore(args.local_artifacts),
                                      CosArtifactStore(settings))
    except (TransferError, ArtifactError, ValueError) as error:
        code = error.code if isinstance(error, (TransferError, ArtifactError)) else 'transfer_configuration_unavailable'
        parser.exit(1, json.dumps({'error': code}) + '\n')
    print(json.dumps(receipt.__dict__, sort_keys=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
