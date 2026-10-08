"""Explicit operator COS write/readback and complete registered-object gate."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import uuid

from .artifacts import ArtifactError, _describe
from .artifact_transfer import TransferError, verify_registered_remote
from .cos_artifacts import CosArtifactStore
from .storage_config import ObjectStorageSettings
from .storage_readiness import initialization_snapshot


def verify_storage(database: Path, store):
    # Each explicit preflight exercises a fresh PUT, rather than dedup-only GET.
    content = json.dumps({'purpose': 'storage-preflight', 'id': uuid.uuid4().hex}).encode()
    manifest = json.dumps({'version': 1, 'files': [{'path': 'probe.json',
        'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}]},
        separators=(',', ':')).encode()
    payload = b'ATOMSNAP1\n' + struct.pack('>I', len(manifest)) + manifest + content
    artifact = _describe(payload)
    if store.put(payload) != artifact or store.read(artifact.key) != payload:
        raise ArtifactError('artifact_digest_mismatch')
    initial = initialization_snapshot()
    marker = _describe(initial)
    if store.put(initial) != marker or store.read(marker.key) != initial:
        raise ArtifactError('artifact_digest_mismatch')
    receipt = verify_registered_remote(database, store)
    return {'ok': True, 'write_readback': True, 'probe_key': artifact.key,
            'initialization_key': marker.key,
            **receipt.__dict__}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    args = parser.parse_args()
    if not args.database.is_absolute():
        parser.exit(2, 'invalid_storage_preflight_database\n')
    try:
        result = verify_storage(args.database, CosArtifactStore(ObjectStorageSettings(_env_file=None)))
    except (ArtifactError, TransferError) as error:
        parser.exit(2, error.code + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
